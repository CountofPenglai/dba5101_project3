import threading
import time
import unittest
import uuid
from unittest.mock import patch

import server_pull
from bandit.client import PacedClient
from bandit.common import SERVER_URL
from test_runner import Clock, FakeServer


class PacingTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.server = FakeServer(self.clock)
        self.delays = iter([])
        server_pull._sessions.clear()

        def request(*args, **kwargs):
            try:
                return self.server.request(*args, **kwargs)
            finally:
                self.clock.value += next(self.delays, 0)

        for target, replacement in (
            ("server_pull._request", request),
            ("bandit.client.time.monotonic", self.clock.monotonic),
            ("bandit.client.time.sleep", self.clock.sleep),
        ):
            mocked = patch(target, replacement)
            mocked.start()
            self.addCleanup(mocked.stop)

    def client(self, interval=0.25):
        return PacedClient("group-a", "test-password", SERVER_URL, interval=interval)

    def starts(self):
        return [row[0] for row in self.server.calls]

    def assert_starts(self, expected):
        self.assertEqual(len(self.starts()), len(expected))
        for actual, target in zip(self.starts(), expected):
            self.assertAlmostEqual(actual, target)

    def test_network_and_local_work_count_toward_start_spacing(self):
        self.delays = iter([0.12, 0.12, 0.12])
        with self.client() as client:
            client.status()
            self.clock.value += 0.03  # Saving results/choosing the next arm.
            client.status()
            client.status()
        self.assert_starts([0.25, 0.50, 0.75])

    def test_slow_request_does_not_add_sleep_or_create_catch_up_burst(self):
        self.delays = iter([0.8, 0, 0])
        with self.client() as client:
            for _ in range(3):
                client.status()
        self.assert_starts([0.25, 1.05, 1.30])

    def test_early_sleep_return_still_observes_minimum_spacing(self):
        sleeps = []

        def interrupted_sleep(seconds):
            sleeps.append(seconds)
            self.clock.value += seconds / 2 if len(sleeps) == 1 else seconds

        with patch("bandit.client.time.sleep", interrupted_sleep), self.client() as client:
            client.status()
            client.status()
        self.assert_starts([0.25, 0.50])

    def test_custom_interval_and_one_second_request_window(self):
        self.delays = iter([0.10] * 12)
        with self.client(interval=0.4) as client:
            for _ in range(12):
                client.status()
        self.assert_starts([0.4 * n for n in range(1, 13)])
        for start in self.starts():
            self.assertLessEqual(sum(start <= t <= start + 1 for t in self.starts()), 5)

    def test_status_and_pull_share_minimum_spacing_and_request_window(self):
        self.delays = iter([0.08] * 13)
        with self.client() as client:
            client.status()
            for index in range(12):
                client.pull({"arm": index, "expected_pull": index, "request_id": str(uuid.uuid4())})
        self.assert_starts([0.25 * n for n in range(1, 14)])
        for start in self.starts():
            self.assertLessEqual(sum(start <= t <= start + 1 for t in self.starts()), 5)

    def test_retry_waits_one_second_after_failure_and_reuses_identity(self):
        self.server.fail_after_commit = 1
        self.delays = iter([0.6, 0])
        request = {"arm": 0, "expected_pull": 0, "request_id": str(uuid.uuid4())}
        with self.client() as client:
            with self.assertRaises(server_pull.UncertainPullError):
                client.pull(request)
            failed_at = self.clock.value
            client.wait_before_retry()
            result = client.pull(request)
        self.assertAlmostEqual(self.starts()[1], failed_at + 1)
        self.assertEqual(self.server.calls[0][2], self.server.calls[1][2])
        self.assertEqual(result["Pull"], 0)
        self.assertEqual(self.server.used, 1)

    def test_precreated_client_waits_when_it_acquires_the_driver(self):
        first, second = self.client(), self.client()
        self.delays = iter([0.05, 0])
        with first:
            first.status()
        with second:
            second.status()
        self.assertGreaterEqual(self.starts()[1] - self.starts()[0], 0.25)

    def test_guard_runs_after_wait_and_spacing_uses_actual_call_time(self):
        self.delays = iter([0.12, 0.12])
        guard_times = []

        def guard():
            guard_times.append(self.clock.value)
            self.clock.value += 0.1

        with self.client() as client:
            client.pull({"arm": 0, "expected_pull": 0, "request_id": str(uuid.uuid4())},
                        before_send=guard)
            client.status()
        self.assertEqual(guard_times, [0.25])
        self.assert_starts([0.35, 0.60])


class ConcurrentPacingTests(unittest.TestCase):
    def test_callers_sharing_a_client_remain_serial_and_paced(self):
        starts, errors = [], []
        barrier = threading.Barrier(3)
        server_pull._sessions.clear()

        def request(*args, **kwargs):
            starts.append(time.monotonic())
            time.sleep(0.03)
            return 200, {"PullsUsed": 0, "NetReward": 0, "MaxPulls": 1_000_000, "Open": True}

        def call(client):
            try:
                barrier.wait(timeout=3)
                client.status()
            except BaseException as error:
                errors.append(type(error).__name__)

        with patch("server_pull._request", request), \
                PacedClient("group-a", "test-password", SERVER_URL) as client:
            workers = [threading.Thread(target=call, args=(client,)) for _ in range(2)]
            for worker in workers:
                worker.start()
            barrier.wait(timeout=3)
            for worker in workers:
                worker.join(timeout=3)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(len(starts), 2)
        # Allow only sub-millisecond interpreter overhead between scheduler/HTTP.
        self.assertGreaterEqual(starts[1] - starts[0], 0.249)


if __name__ == "__main__":
    unittest.main()
