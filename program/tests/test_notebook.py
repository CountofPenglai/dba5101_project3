import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import server_pull
from bandit import save_results
from bandit.storage import HistoryStore
from test_runner import Clock, FakeServer


PROGRAM = Path(__file__).resolve().parents[1]
NOTEBOOK = PROGRAM / "GP3 Run.ipynb"


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(NOTEBOOK.is_file(), "The operational notebook has not been created")
        self.notebook = json.loads(NOTEBOOK.read_text())
        self.cells = {cell["metadata"]["tags"][0]: cell for cell in self.notebook["cells"]
                      if cell["cell_type"] == "code"}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "history.sqlite3"
        self.output = io.StringIO()
        self.displays = []
        self.ns = {"__name__": "__main__"}
        # Stub only the rendering boundary; these tests need no Jupyter installation.
        display_module = types.ModuleType("IPython.display")
        display_module.HTML = lambda data: types.SimpleNamespace(data=data)
        display_module.display = lambda value: self.displays.append(value.data)
        ipython_module = types.ModuleType("IPython")
        ipython_module.display = display_module
        modules = patch.dict(sys.modules, {"IPython": ipython_module, "IPython.display": display_module})
        modules.start()
        self.addCleanup(modules.stop)
        self.clock = Clock()
        self.server = FakeServer(self.clock)
        server_pull._sessions.clear()
        for target, replacement in (
            ("server_pull._request", self.server.request),
            ("bandit.client.time.monotonic", self.clock.monotonic),
            ("bandit.client.time.sleep", self.clock.sleep),
            ("bandit.runner.utc_now", lambda: datetime(2026, 11, 1, tzinfo=timezone.utc)),
            ("getpass.getpass", lambda *args: self.fail("Unexpected password prompt")),
            ("builtins.input", lambda *args: self.fail("Unexpected username prompt")),
        ):
            mocked = patch(target, replacement)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.execute("config")
        self.ns["DB_PATH"] = str(self.db)
        self.execute("setup")

    def execute(self, tag):
        source = "".join(self.cells[tag]["source"])
        with redirect_stdout(self.output):
            exec(compile(source, str(NOTEBOOK) + "#" + tag, "exec"), self.ns)

    def test_default_run_all_is_offline_and_shipped_outputs_are_clean(self):
        self.assertFalse(self.ns["ONLINE"])
        self.execute("run")
        self.execute("inspect")
        self.execute("log")
        self.assertEqual(self.ns["last_run_summary"]["completed_pulls"], 0)
        self.assertEqual(self.ns["snapshot"]["history_pulls"], 0)
        self.assertEqual(len(self.ns["snapshot"]["arms"]), 24)
        self.assertEqual(self.server.calls, [])
        for cell in self.cells.values():
            self.assertEqual(cell["outputs"], [])
            self.assertIsNone(cell["execution_count"])

    def test_inspection_without_running_does_not_create_database(self):
        self.execute("inspect")
        self.execute("log")
        self.assertFalse(self.db.exists())
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.ns["snapshot"]["history_pulls"], 0)

    def test_inspection_refreshes_saved_data_and_has_bounded_recent_rows(self):
        save_results([{"Arm": "0", "Reward": 20, "NetReward": 20, "Pull": 0}],
                     username="group-a", db_path=self.db)
        self.ns.update(ONLINE=True, MODEL_NAME="ucb", UCB_EXPLORATION=0.5, DISPLAY_ROWS=1)
        self.execute("inspect")
        self.assertEqual(self.ns["snapshot"]["history_signups"], 20)
        save_results([{"Arm": "1", "Reward": 30, "NetReward": 50, "Pull": 1}],
                     username="group-a", db_path=self.db)
        self.execute("inspect")
        snapshot = self.ns["snapshot"]
        self.assertEqual(snapshot["history_pulls"], 2)
        self.assertEqual(snapshot["history_signups"], 50)
        self.assertEqual(snapshot["arms"][1]["visitors"], 100)
        self.assertEqual(snapshot["arms"][1]["conversion_rate"], 0.3)
        self.assertEqual(snapshot["arms"][1]["allocation_share"], 0.5)
        self.assertEqual([r["Pull"] for r in snapshot["recent"]], [1])
        self.assertEqual(snapshot["identity"]["username"], "group-a")
        self.assertEqual(self.server.calls, [])
        self.assertIn("UCB index", "".join(self.displays))

    def test_online_configuration_reaches_real_runner_and_keeps_secret_local(self):
        self.ns.update(ONLINE=True, MODEL_NAME="ucb", UCB_EXPLORATION=0.75, BUDGET=2,
                       GROUP_USERNAME="", REQUEST_INTERVAL=0.5,
                       getpass=lambda prompt: "notebook-test-secret",
                       input=lambda prompt: "group-a")
        self.execute("run")
        self.assertEqual(self.ns["last_run_summary"]["completed_pulls"], 2)
        self.assertEqual(self.ns["last_run_summary"]["parameters"], {"exploration": 0.75})
        moments = [call[0] for call in self.server.calls]
        self.assertTrue(all(b - a >= 0.5 for a, b in zip(moments, moments[1:])))
        self.execute("inspect")
        self.execute("log")
        self.assertEqual(self.server.used, 2)
        self.assertEqual(self.ns["snapshot"]["history_pulls"], 2)
        self.assertNotIn("notebook-test-secret", self.output.getvalue() + "".join(self.displays))
        self.assertNotIn("notebook-test-secret", [v for v in self.ns.values() if isinstance(v, str)])
        self.assertNotIn(b"notebook-test-secret", self.db.read_bytes())
        self.assertNotIn("notebook-test-secret", self.db.with_suffix(".online.jsonl").read_text())

    def test_failed_rerun_clears_previous_summary_and_keeps_recovery_inspectable(self):
        self.ns.update(ONLINE=True, BUDGET=1, GROUP_USERNAME="group-a", MAX_RETRIES=0,
                       getpass=lambda prompt: "notebook-test-secret")
        self.execute("run")
        self.assertEqual(self.ns["last_run_summary"]["completed_pulls"], 1)
        self.server.fail_after_commit = 1
        self.execute("run")
        self.assertIsNone(self.ns["last_run_summary"])
        self.assertEqual(self.ns["run_error"], "UncertainPullError")
        self.execute("inspect")
        self.assertIsNotNone(self.ns["snapshot"]["pending"])
        self.assertEqual(self.ns["snapshot"]["history_pulls"], 1)

    def test_invalid_settings_fail_before_credentials_or_http(self):
        self.ns.update(ONLINE=True, BUDGET=-1)
        self.execute("run")
        self.assertIsNone(self.ns["last_run_summary"])
        self.assertEqual(self.ns["run_error"], "ValueError")
        self.assertEqual(self.server.calls, [])

    def test_rejected_run_settings_do_not_block_saved_history_or_log_views(self):
        save_results([{"Arm": "0", "Reward": 20, "NetReward": 20, "Pull": 0}],
                     username="group-a", db_path=self.db)
        self.db.with_suffix(".online.jsonl").write_text(
            json.dumps({"event": "run_finished", "stop_reason": "budget_complete"}) + "\n")
        self.ns.update(ONLINE=True, BUDGET=-1, REQUEST_TIMEOUT=0, MAX_RETRIES=-1,
                       GROUP_USERNAME=None)
        self.execute("run")
        self.assertEqual(self.ns["run_error"], "ValueError")
        self.execute("inspect")
        self.execute("log")
        self.assertEqual(self.ns["snapshot"]["history_pulls"], 1)
        self.assertIn("budget_complete", "".join(self.displays))
        self.assertEqual(self.server.calls, [])

    def test_log_view_does_not_depend_on_model_or_result_table_settings(self):
        self.ns.update(MODEL_NAME="typo", UCB_EXPLORATION=-1, DISPLAY_ROWS=-1)
        self.execute("log")
        self.assertIn("No online log yet", self.output.getvalue())
        self.assertEqual(self.server.calls, [])

    def test_zero_budget_online_does_not_prompt(self):
        self.ns.update(ONLINE=True, BUDGET=0)
        self.execute("run")
        self.assertEqual(self.ns["last_run_summary"]["stop_reason"], "zero_budget")
        self.assertEqual(self.server.calls, [])

    def test_log_tail_handles_partial_line_and_escapes_html(self):
        self.ns["LOG_ROWS"] = 2
        path = self.db.with_suffix(".online.jsonl")
        path.write_text('\n'.join(json.dumps({"event": event, "timestamp": "now", "run_id": "r"})
                                  for event in ("old", "<script>alert(1)</script>")) + '\n{"partial":')
        self.execute("log")
        rendered = "".join(self.displays)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn('>old<', rendered)
        self.assertIn("incomplete", self.output.getvalue().lower())
        self.assertEqual(self.server.calls, [])

    def test_program_paths_resolve_from_project_and_parent_directories(self):
        old = Path.cwd()
        try:
            for cwd in (PROGRAM.parent, PROGRAM.parent.parent):
                os.chdir(cwd)
                self.ns["DB_PATH"] = "data/history.sqlite3"
                self.execute("setup")
                self.assertEqual(self.ns["resolved_settings"]()["db_path"], PROGRAM / "data/history.sqlite3")
        finally:
            os.chdir(old)


if __name__ == "__main__":
    unittest.main()
