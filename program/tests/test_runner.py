import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import server_pull
from bandit.storage import HistoryStore
from bandit.common import DEADLINE

try:
    from bandit import run_experiment, save_results
except ImportError:
    run_experiment = save_results = None


class Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeServer:
    """Replace only HTTP I/O; exercise the supplied client's real recovery logic."""
    def __init__(self, clock):
        self.clock = clock
        self.used = 0
        self.total = 0
        self.open = True
        self.maximum = 1_000_000
        self.calls = []
        self.receipts = {}
        self.fail_after_commit = 0
        self.fail_before_commit = False
        self.reject = False

    def request(self, username, password, path, timeout, data=None):
        self.calls.append((self.clock.value, path, dict(data) if data else None))
        if path == "/v1/status":
            return 200, {"PullsUsed": self.used, "NetReward": self.total,
                         "MaxPulls": self.maximum, "Open": self.open}
        if self.reject:
            return 409, {"message": "private-test-password must not appear in logs"}
        if self.fail_before_commit:
            raise ConnectionError("uncertain")
        key = data["request_id"]
        if key in self.receipts:
            old_payload, response = self.receipts[key]
            if old_payload != data:
                return 409, {"message": "Changed recovery payload"}
            return 200, {"result": response}
        if data["expected_pull"] != self.used:
            return 409, {"message": "Counter conflict"}
        if not self.open or self.used >= self.maximum:
            return 403, {"message": "Closed"}
        self.total += 20
        response = {"Arm": str(data["arm"]), "Reward": 20,
                    "NetReward": self.total, "Pull": self.used}
        self.used += 1
        self.receipts[key] = (dict(data), response)
        if self.fail_after_commit:
            self.fail_after_commit -= 1
            raise ConnectionError("Response lost after server commit")
        return 200, {"result": response}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(run_experiment, "Experiment driver has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "group.sqlite3"
        self.log = self.path.with_suffix(".online.jsonl")
        self.clock = Clock()
        self.server = FakeServer(self.clock)
        # Each test has a new fake server, unlike two invocations within a test.
        server_pull._sessions.clear()
        for target, replacement in (
            ("server_pull._request", self.server.request),
            ("bandit.client.time.monotonic", self.clock.monotonic),
            ("bandit.client.time.sleep", self.clock.sleep),
            ("bandit.runner.utc_now", lambda: datetime(2026, 11, 1, tzinfo=timezone.utc)),
        ):
            mocked = patch(target, replacement)
            mocked.start()
            self.addCleanup(mocked.stop)

    def run_online(self, budget=3, **kwargs):
        return run_experiment("uniform", budget, online=True, db_path=self.path,
                              username="group-a", password="private-test-password", **kwargs)

    def records(self):
        with HistoryStore(self.path) as store:
            return list(store.results())

    def test_offline_fits_saved_history_without_network_or_new_results(self):
        save_results([{"Arm": "0", "Reward": 30, "NetReward": 30, "Pull": 0}],
                     db_path=self.path, username="group-a")
        summary = run_experiment("ucb", 500, db_path=self.path)
        self.assertEqual(summary["completed_pulls"], 0)
        self.assertEqual(summary["history_pulls"], 1)
        self.assertEqual(summary["next_arm"], 1)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.server.calls, [])
        self.assertFalse(self.log.exists())

    def test_online_budget_appends_results_and_resumes_model_history(self):
        first = self.run_online(3)
        second = self.run_online(2)
        self.assertEqual(first["completed_pulls"], 3)
        self.assertEqual(second["completed_pulls"], 2)
        self.assertEqual(second["history_pulls"], 5)
        self.assertEqual([row["Arm"] for row in self.records()], ["0", "1", "2", "3", "4"])
        self.assertEqual(self.server.used, 5)
        self.assertEqual(second["stop_reason"], "budget_complete")

    def test_status_and_pull_calls_are_paced_including_across_runs(self):
        self.run_online(3)
        self.run_online(1)
        moments = [call[0] for call in self.server.calls]
        self.assertTrue(all(b - a >= 0.25 for a, b in zip(moments, moments[1:])))

    def test_uncertain_retry_reuses_identity_waits_and_deduplicates(self):
        self.server.fail_after_commit = 1
        summary = self.run_online(2)
        pulls = [call for call in self.server.calls if call[1] == "/v1/pull"]
        self.assertEqual(pulls[0][2], pulls[1][2])
        self.assertGreaterEqual(pulls[1][0] - pulls[0][0], 1)
        self.assertEqual(summary["completed_pulls"], 2)
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.server.used, 2)

    def test_restart_recovers_before_new_selection_and_counts_against_budget(self):
        self.server.fail_after_commit = 1
        with self.assertRaises(server_pull.UncertainPullError):
            self.run_online(10, max_retries=0)
        with HistoryStore(self.path) as store:
            pending = store.pending
            self.assertEqual(list(store.results()), [])
        summary = self.run_online(1)
        self.assertEqual(summary["completed_pulls"], 1)
        self.assertEqual(self.server.used, 1)
        self.assertEqual(self.records()[0]["Pull"], pending["expected_pull"])
        with HistoryStore(self.path) as store:
            self.assertIsNone(store.pending)

    def test_request_identity_is_durable_before_http_starts(self):
        original = self.server.request
        def inspect(username, password, path, timeout, data=None):
            if path == "/v1/pull":
                with HistoryStore(self.path) as store:
                    self.assertEqual(store.pending["request_id"], data["request_id"])
            return original(username, password, path, timeout, data)
        with patch("server_pull._request", inspect):
            self.run_online(1)

    def test_bounded_failure_preserves_pending_and_logs_no_secret(self):
        self.server.fail_before_commit = True
        with self.assertRaises(server_pull.UncertainPullError):
            self.run_online(3, max_retries=2)
        self.assertEqual(len([c for c in self.server.calls if c[1] == "/v1/pull"]), 3)
        with HistoryStore(self.path) as store:
            self.assertIsNotNone(store.pending)
        self.assertEqual(self.records(), [])
        self.assertNotIn("private-test-password", self.log.read_text())

    def test_rejection_retains_pending_and_does_not_log_remote_message(self):
        self.server.reject = True
        with self.assertRaises(RuntimeError):
            self.run_online(2)
        with HistoryStore(self.path) as store:
            self.assertIsNotNone(store.pending)
        self.assertNotIn("private-test-password", self.log.read_text())
        self.assertNotIn(b"private-test-password", self.path.read_bytes())

    def test_budget_zero_and_offline_pending_do_not_send_requests(self):
        self.server.fail_after_commit = 1
        with self.assertRaises(server_pull.UncertainPullError):
            self.run_online(2, max_retries=0)
        before = len(self.server.calls)
        self.assertEqual(self.run_online(0)["completed_pulls"], 0)
        offline = run_experiment("ucb", 20, db_path=self.path)
        self.assertIsNotNone(offline["pending_request"])
        self.assertEqual(offline["next_arm"], 0)
        self.assertEqual(len(self.server.calls), before)

    def test_group_remaining_budget_caps_new_pulls(self):
        self.server.used = 999_998
        self.server.total = 19_999_960
        summary = self.run_online(5)
        self.assertEqual(summary["completed_pulls"], 2)
        self.assertEqual(summary["stop_reason"], "group_budget_exhausted")
        self.assertEqual(self.server.used, 1_000_000)

    def test_closed_server_prevents_new_pulls(self):
        self.server.open = False
        summary = self.run_online(1)
        self.assertEqual(summary["stop_reason"], "server_closed")
        self.assertEqual(summary["completed_pulls"], 0)

    def test_deadline_prevents_new_pulls_but_allows_recovery(self):
        self.server.fail_after_commit = 1
        with self.assertRaises(server_pull.UncertainPullError):
            self.run_online(1, max_retries=0)
        with patch("bandit.runner.utc_now", lambda: datetime(2026, 11, 16, tzinfo=timezone.utc)):
            summary = self.run_online(5)
            self.assertEqual(summary["completed_pulls"], 1)
            self.assertEqual(summary["stop_reason"], "deadline_reached")
            empty = Path(self.tmp.name) / "empty.sqlite3"
            before = len(self.server.calls)
            summary = run_experiment("ucb", 2, online=True, db_path=empty,
                                     username="group-a", password="private-test-password")
            self.assertEqual(summary["completed_pulls"], 0)
            self.assertEqual(len(self.server.calls), before)

    def test_deadline_crossed_during_pacing_cancels_unsent_request(self):
        def now():
            return DEADLINE - timedelta(seconds=1.5) + timedelta(seconds=self.clock.value)
        with patch("bandit.runner.utc_now", now):
            summary = self.run_online(1, interval=1.0)
        self.assertEqual(summary["completed_pulls"], 0)
        self.assertEqual(summary["stop_reason"], "deadline_reached")
        self.assertEqual([call[1] for call in self.server.calls], ["/v1/status"])
        with HistoryStore(self.path) as store:
            self.assertIsNone(store.pending)
        events = [json.loads(line)["event"] for line in self.log.read_text().splitlines()]
        self.assertIn("pull_cancelled", events)

    def test_audit_log_appends_across_runs_and_contains_results(self):
        self.run_online(1)
        prefix = self.log.read_bytes()
        self.run_online(1)
        self.assertTrue(self.log.read_bytes().startswith(prefix))
        events = [json.loads(line) for line in self.log.read_text().splitlines()]
        results = [e for e in events if e["event"] == "pull_completed"]
        self.assertEqual([e["result"]["Pull"] for e in results], [0, 1])
        self.assertTrue(all("timestamp" in e and "run_id" in e for e in events))
        self.assertNotIn("private-test-password", self.log.read_text())

    def test_invalid_settings_rejected_before_network(self):
        for kwargs in ({"interval": 0.1}, {"interval": float("nan")},
                       {"timeout": 0}, {"max_retries": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_online(**kwargs)
        for budget in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                self.run_online(budget)
        self.assertEqual(self.server.calls, [])

    def test_log_path_cannot_alias_database(self):
        with self.assertRaises(ValueError):
            self.run_online(log_path=self.path)
        self.assertEqual(self.server.calls, [])


if __name__ == "__main__":
    unittest.main()
