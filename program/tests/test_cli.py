import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROGRAM = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "test.sqlite3"

    def cli(self, *args):
        env = dict(os.environ)
        env.pop("GP3_PASSWORD", None)
        return subprocess.run([sys.executable, "-m", "bandit", *map(str, args)],
                              cwd=PROGRAM, capture_output=True, text=True, env=env, timeout=10)

    def test_default_offline_run_needs_no_credentials(self):
        process = self.cli("run", "--model", "ucb", "--budget", "50", "--db", self.path)
        self.assertEqual(process.returncode, 0, process.stderr)
        summary = json.loads(process.stdout)
        self.assertFalse(summary["online"])
        self.assertEqual(summary["completed_pulls"], 0)
        self.assertEqual(summary["next_arm"], 0)

    def test_import_train_and_export_real_response_format(self):
        source = Path(self.tmp.name) / "source.jsonl"
        row = {"Arm": "0", "Reward": 25, "NetReward": 25, "Pull": 0}
        source.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
        imported = self.cli("import-results", source, "--group", "group-a", "--db", self.path)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.assertEqual(json.loads(imported.stdout)["inserted"], 1)
        trained = self.cli("run", "--model", "ucb", "--exploration", "0.5", "--db", self.path)
        self.assertEqual(trained.returncode, 0, trained.stderr)
        summary = json.loads(trained.stdout)
        self.assertEqual(summary["parameters"], {"exploration": 0.5})
        self.assertEqual(summary["arms"][0]["conversion_rate"], 0.25)
        target = Path(self.tmp.name) / "export.jsonl"
        exported = self.cli("export-results", target, "--db", self.path)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertEqual(json.loads(target.read_text()), row)

    def test_zero_budget_online_does_not_prompt_for_password(self):
        process = self.cli("run", "--online", "--budget", "0", "--db", self.path)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["stop_reason"], "zero_budget")

    def test_invalid_budget_fails_without_network(self):
        process = self.cli("run", "--budget", "-1", "--db", self.path)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("budget", process.stderr.lower())

    def test_malformed_import_rolls_back_prior_lines(self):
        source = Path(self.tmp.name) / "source.jsonl"
        source.write_text('{"Arm":"0","Reward":20,"NetReward":20,"Pull":0}\nnot-json\n')
        imported = self.cli("import-results", source, "--group", "group-a", "--db", self.path)
        self.assertNotEqual(imported.returncode, 0)
        trained = self.cli("run", "--db", self.path)
        self.assertEqual(trained.returncode, 0, trained.stderr)
        self.assertEqual(json.loads(trained.stdout)["history_pulls"], 0)


if __name__ == "__main__":
    unittest.main()
