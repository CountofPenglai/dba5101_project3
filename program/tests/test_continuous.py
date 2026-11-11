import json
import threading
import unittest
from unittest.mock import patch

from bandit import UCBModel, run_experiment
from bandit.storage import HistoryStore
from bandit.tuning import TuningConfig
import test_runner as helpers


class ContinuousTests(unittest.TestCase):
    setUp = helpers.RunnerTests.setUp
    run_online = helpers.RunnerTests.run_online
    records = helpers.RunnerTests.records
    def test_none_budget_uses_server_remaining_and_absolute_cap(self):
        self.server.maximum = 7
        summary = self.run_online(None, target_total=5)
        self.assertEqual(summary['completed_pulls'], 5)
        self.assertEqual(summary['stop_reason'], 'target_reached')
        summary = self.run_online(None)
        self.assertEqual(summary['completed_pulls'], 2)
        self.assertEqual(summary['stop_reason'], 'group_budget_exhausted')

    def test_stop_during_http_saves_response_before_exiting(self):
        event = threading.Event()
        original = self.server.request
        def request(*args, **kwargs):
            response = original(*args, **kwargs)
            if args[2] == '/v1/pull':
                event.set()
            return response
        with patch('server_pull._request', request):
            summary = self.run_online(None, stop_event=event)
        self.assertEqual(summary['stop_reason'], 'manual_stop')
        self.assertEqual(summary['completed_pulls'], 1)
        with HistoryStore(self.path) as store:
            self.assertIsNone(store.pending)
        self.assertEqual(len(self.records()), 1)

    def test_stop_during_lost_response_preserves_original_request(self):
        event = threading.Event()
        original = self.server.request
        self.server.fail_after_commit = 1
        def request(*args, **kwargs):
            if args[2] == '/v1/pull':
                event.set()
            return original(*args, **kwargs)
        with patch('server_pull._request', request):
            summary = self.run_online(None, stop_event=event, max_retries=None)
        self.assertEqual(summary['completed_pulls'], 0)
        with HistoryStore(self.path) as store:
            identity = store.pending['request_id']
        recovered = self.run_online(1)
        self.assertEqual(recovered['completed_pulls'], 1)
        self.assertEqual(self.server.used, 1)
        self.assertEqual(list(self.server.receipts), [identity])

    def test_tuning_schedule_and_coefficient_survive_restart_and_disabled_means_fixed(self):
        self.run_online(24)
        cfg = TuningConfig(interval=4)
        calls = []
        def evaluate(stats, remaining, baseline, config, stop):
            calls.append(sum(r['pulls'] for r in stats))
            return {'selected_multiplier': .03, 'reason': 'test'}
        def run(count, tune=cfg):
            return run_experiment(UCBModel(.005), count, online=True, db_path=self.path,
                                  username='group-a', password='private-test-password', tuning=tune)
        with patch('bandit.runner.evaluate_isolated', evaluate):
            first = run(2)
            second = run(3)
            disabled = run(1, None)
        self.assertEqual(calls, [24, 28])
        self.assertEqual(first['parameters']['exploration'], .0018)
        self.assertEqual(second['parameters']['exploration'], .0018)
        self.assertEqual(disabled['parameters']['exploration'], .005)
        with HistoryStore(self.path) as store:
            self.assertEqual(store.tuning_state()['next_at'], 32)
            rows = store.connection.execute('select parameters from results where pull>=24 and pull<29')
            self.assertTrue(all(json.loads(row[0])['exploration'] == .0018 for row in rows))

    def test_no_tuning_before_pending_recovery_or_in_offline_mode(self):
        self.run_online(24)
        self.server.fail_after_commit = 1
        import server_pull
        with self.assertRaises(server_pull.UncertainPullError):
            self.run_online(1, max_retries=0)
        cfg = TuningConfig(interval=4)
        with patch('bandit.runner.evaluate_isolated') as evaluate:
            run_experiment(UCBModel(.005), None, db_path=self.path, tuning=cfg)
            evaluate.assert_not_called()
        def evaluate(stats, remaining, baseline, config, stop):
            with HistoryStore(self.path) as store:
                self.assertIsNone(store.pending)
            self.assertEqual(sum(row['pulls'] for row in stats), 25)
            return {'selected_multiplier': baseline, 'reason': 'test'}
        with patch('bandit.runner.evaluate_isolated', evaluate):
            run_experiment(UCBModel(.005), 2, online=True, db_path=self.path,
                           username='group-a', password='private-test-password', tuning=cfg)

    def test_strict_history_check_rejects_unsaved_server_results(self):
        self.server.used = 10
        self.server.total = 200
        with self.assertRaises(RuntimeError):
            self.run_online(None, strict_history=True)
        self.assertEqual(self.server.used, 10)

    def test_absolute_cap_does_not_send_an_unresolved_request_beyond_cap(self):
        self.server.fail_before_commit = True
        import server_pull
        with self.assertRaises(server_pull.UncertainPullError):
            self.run_online(1, max_retries=0)
        calls = len(self.server.calls)
        self.server.fail_before_commit = False
        summary = self.run_online(None, target_total=0)
        self.assertEqual(summary['stop_reason'], 'target_reached')
        self.assertEqual(len(self.server.calls), calls)
        self.assertIsNotNone(summary['pending_request'])

    def test_sigterm_during_response_is_saved_and_handler_restored(self):
        import signal
        previous = signal.getsignal(signal.SIGTERM)
        original = self.server.request
        def request(*args, **kwargs):
            response = original(*args, **kwargs)
            if args[2] == '/v1/pull':
                signal.raise_signal(signal.SIGTERM)
            return response
        with patch('server_pull._request', request):
            summary = self.run_online(None)
        self.assertEqual(summary['completed_pulls'], 1)
        self.assertEqual(summary['stop_reason'], 'manual_stop')
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)
        self.assertIsNone(summary['pending_request'])

    def test_online_runner_trains_from_aggregates_not_response_scan(self):
        self.run_online(30)
        with patch.object(HistoryStore, 'results', side_effect=AssertionError('full scan')):
            summary = self.run_online(1)
        self.assertEqual(summary['history_pulls'], 31)
