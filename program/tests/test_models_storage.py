import json
import tempfile
import unittest
from pathlib import Path

try:
    from bandit.models import UniformModel, UCBModel
    from bandit.storage import HistoryStore, driver_lock
except ImportError:
    UniformModel = UCBModel = HistoryStore = driver_lock = None


def result(pull, arm=0, reward=20, total=None):
    return {"Arm": str(arm), "Reward": reward,
            "NetReward": reward * (pull + 1) if total is None else total, "Pull": pull}


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(UniformModel, "Bandit models have not been implemented")

    def test_uniform_balances_saved_counts_and_fit_resets(self):
        model = UniformModel().fit([result(0), result(1), result(2, arm=1)])
        self.assertEqual(model.select_arm(), 2)
        self.assertEqual(model.summary()[0]["pulls"], 2)
        model.fit([result(0)])
        self.assertEqual(model.total_pulls, 1)
        self.assertEqual(model.summary()[1]["pulls"], 0)

    def test_ucb_prioritizes_unseen_arms_then_uses_normalized_rewards(self):
        model = UCBModel(exploration=2).fit([result(0, arm=0, reward=100)])
        self.assertEqual(model.select_arm(), 1)
        model.fit([result(i, arm=i, reward=40 if i == 7 else 10,
                          total=10 * (i + 1) + (30 if i >= 7 else 0))
                   for i in range(24)])
        self.assertEqual(model.select_arm(), 7)
        # All arms have one batch: sqrt(2 log(24)) = 2.5211322180.
        self.assertAlmostEqual(model.summary()[7]["score"], 2.9211322180, places=8)
        self.assertAlmostEqual(model.summary()[0]["conversion_rate"], 0.1)

    def test_ucb_explores_a_less_sampled_competitor(self):
        rows = [result(i, arm=i, reward=20) for i in range(24)]
        rows.extend(result(24 + i, arm=0, reward=50, total=480 + 50 * (i + 1)) for i in range(100))
        model = UCBModel().fit(rows)
        self.assertEqual(model.select_arm(), 1)

    def test_invalid_model_settings_and_results_are_rejected(self):
        for value in (0, -1, True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                UCBModel(exploration=value)
        for change in ({"Arm": 24}, {"Reward": 101}, {"Reward": True}, {"Pull": -1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                UniformModel().update({**result(0), **change})

    def test_empty_model_summary_is_json_serializable(self):
        model = UCBModel().fit([])
        self.assertEqual(model.select_arm(), 0)
        json.dumps(model.summary(), allow_nan=False)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(HistoryStore, "History storage has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "history.sqlite3"

    def store(self):
        store = HistoryStore(self.path)
        self.addCleanup(store.close)
        store.bind("group-a", "https://example.test")
        return store

    def test_append_persists_deduplicates_and_rejects_conflict(self):
        store = self.store()
        self.assertTrue(store.append_result(result(0)))
        self.assertFalse(store.append_result(result(0)))
        with self.assertRaises(ValueError):
            store.append_result(result(0, reward=30))
        with HistoryStore(self.path) as reopened:
            self.assertEqual(list(reopened.results()), [result(0)])

    def test_identity_cannot_mix_groups_or_servers(self):
        store = self.store()
        for group, url in (("group-b", "https://example.test"),
                           ("group-a", "https://different.test")):
            with self.assertRaises(ValueError):
                store.bind(group, url)
        self.assertEqual(store.identity["username"], "group-a")

    def test_pending_survives_restart_and_complete_is_atomic(self):
        store = self.store()
        request = store.prepare(arm=2, expected_pull=3, model="uniform", parameters={})
        with HistoryStore(self.path) as reopened:
            self.assertEqual(reopened.pending, request)
            with self.assertRaises(ValueError):
                reopened.complete(result(3, arm=1))
            self.assertEqual(reopened.pending, request)
            self.assertEqual(list(reopened.results()), [])
            reopened.complete(result(3, arm=2))
            self.assertIsNone(reopened.pending)
            self.assertEqual(list(reopened.results()), [result(3, arm=2)])

    def test_import_is_atomic_and_supports_gaps(self):
        store = self.store()
        with self.assertRaises(ValueError):
            store.import_results([result(0), {**result(1), "Reward": 200}])
        self.assertEqual(list(store.results()), [])
        self.assertEqual(store.import_results([result(3), result(0), result(0)]), 2)
        self.assertEqual([row["Pull"] for row in store.results()], [0, 3])

    def test_local_driver_lock_blocks_another_driver(self):
        with driver_lock(self.path):
            with self.assertRaises(RuntimeError):
                with driver_lock(self.path):
                    self.fail("Second driver acquired the same history")

    def test_export_preserves_only_result_fields(self):
        store = self.store()
        store.append_result({**result(0), "password": "do-not-save"})
        target = Path(self.tmp.name) / "results.jsonl"
        self.assertEqual(store.export_jsonl(target), 1)
        self.assertEqual(json.loads(target.read_text()), result(0))
        self.assertNotIn(b"do-not-save", self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
