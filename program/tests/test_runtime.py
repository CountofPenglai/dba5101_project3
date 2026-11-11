import json
import signal
import tempfile
import unittest
import types
from unittest.mock import patch
from pathlib import Path

from bandit import UCBModel
from bandit.storage import HistoryStore, driver_lock
from bandit.audit import OnlineLog


class RuntimeTests(unittest.TestCase):
    def test_aggregate_training_matches_replay_and_tuning_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.sqlite3'
            with HistoryStore(path) as store:
                store.bind('test', 'https://example.org')
                rows = [{'Pull': i, 'Arm': str(i % 24), 'Reward': 20,
                         'NetReward': 20 * (i + 1)} for i in range(250)]
                store.import_results(rows)
                model = UCBModel(.005).fit_aggregates(store.aggregate())
                self.assertEqual(model.summary(), UCBModel(.005).fit(rows).summary())
                store.record_tuning({'at_pull': 250, 'next_at': 450,
                                     'selected_multiplier': .03, 'config_key': 'test'})
            with HistoryStore(path) as store:
                self.assertEqual(store.tuning_state()['next_at'], 450)
                self.assertEqual(store.tuning_state()['selected_multiplier'], .03)
                self.assertEqual(store.connection.execute('select count(*) from tuning_decisions').fetchone()[0], 1)

    def test_log_append_after_torn_line_preserves_new_events(self):
        from bandit.audit import tail_lines
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'audit.jsonl'
            path.write_bytes(b'{"event":"old"}\n{"partial":')
            with OnlineLog(path, 'r') as log:
                log.write('new')
            lines = tail_lines(path, 2)
            self.assertEqual(json.loads(lines[-1])['event'], 'new')
            self.assertIn('partial', lines[0])

    def test_stop_signal_is_graceful_then_forceful_and_restores_handlers(self):
        from bandit.control import StopController
        original = signal.getsignal(signal.SIGTERM)
        with StopController() as stop:
            signal.raise_signal(signal.SIGTERM)
            self.assertTrue(stop.is_set())
            with self.assertRaises(KeyboardInterrupt):
                signal.raise_signal(signal.SIGTERM)
        self.assertIs(signal.getsignal(signal.SIGTERM), original)

    def test_tuning_cannot_be_committed_with_a_pending_request(self):
        with tempfile.TemporaryDirectory() as folder:
            with HistoryStore(Path(folder) / 'history.sqlite3') as store:
                store.bind('test', 'https://example.org')
                store.prepare(arm=0, expected_pull=0, model='ucb', parameters={'exploration': .005})
                with self.assertRaises(RuntimeError):
                    store.record_tuning({'at_pull': 0, 'next_at': 20})

    def test_bad_cumulative_reward_preserves_pending_for_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            with HistoryStore(Path(folder)/'history.sqlite3') as store:
                store.bind('test', 'https://example.org')
                store.append_result({'Arm':'0','Pull':0,'Reward':20,'NetReward':20})
                pending = store.prepare(arm=1,expected_pull=1,model='ucb',parameters={'exploration':.005})
                with self.assertRaises(ValueError):
                    store.complete({'Arm':'1','Pull':1,'Reward':30,'NetReward':49})
                self.assertEqual(store.pending['request_id'],pending['request_id'])
                self.assertEqual(store.last_pull,0)

    def test_windows_fallback_locks_and_unlocks_one_byte(self):
        import os
        calls = []
        def locking(fd, mode, length):
            calls.append((mode, length, os.lseek(fd, 0, os.SEEK_CUR), os.fstat(fd).st_size))
        fake = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=locking)
        with tempfile.TemporaryDirectory() as folder, patch.dict('sys.modules', {'fcntl': None, 'msvcrt': fake}):
            path = Path(folder)/'history.sqlite3'
            with driver_lock(path):
                self.assertEqual(calls, [(2, 1, 0, 1)])
            self.assertEqual(calls, [(2, 1, 0, 1), (0, 1, 0, 1)])


if __name__ == '__main__':
    unittest.main()
