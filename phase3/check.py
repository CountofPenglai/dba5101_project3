"""Check phase 3 end to end against a fake server. No network and no real pulls.

    python check.py

Each check runs main.py on a temporary copy of the database, with the supplied helper's
HTTP call replaced by a fake server whose true rates are the pilot's. The real database is
only read, and the last check confirms it is unchanged.
"""

import contextlib
import hashlib
import io
import random
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import config
import main

import server_pull  # noqa: E402  (importable once main has loaded phase 1)
from bandit import UCBModel  # noqa: E402

REAL_DB = main.resolve_path(config.DB_PATH)
FAILURES = []


class Clock:
    """Fake time, so the 0.25-second gaps between requests don't really wait."""

    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeServer:
    """Answers status and pull like the real server. Each arm's true rate is its pilot rate."""

    def __init__(self, used, total, rates, lose_responses=0):
        self.used, self.total, self.rates = used, total, rates
        self.rng = random.Random(5101)
        self.receipts = {}
        self.status_calls = self.pull_calls = 0
        self.lose_responses = lose_responses

    def request(self, username, password, path, timeout, data=None):
        if path == "/v1/status":
            self.status_calls += 1
            return 200, {"PullsUsed": self.used, "NetReward": self.total, "MaxPulls": 1_000_000, "Open": True}
        self.pull_calls += 1
        if data["request_id"] in self.receipts:  # A retry of a request the server already counted
            return 200, {"result": self.receipts[data["request_id"]]}
        if data["expected_pull"] != self.used:
            return 409, {"message": "Counter conflict"}
        reward = sum(self.rng.random() < self.rates[data["arm"]] for _ in range(100))
        self.total += reward
        result = {"Arm": str(data["arm"]), "Reward": reward, "NetReward": self.total, "Pull": self.used}
        self.used += 1
        self.receipts[data["request_id"]] = result
        if self.lose_responses:
            self.lose_responses -= 1
            raise ConnectionError("Response lost after the server counted the pull")
        return 200, {"result": result}


def no_network(*args, **kwargs):
    raise AssertionError("check.py tried to reach the network")


def report(name, ok, detail):
    print("{}  {}: {}".format("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILURES.append(name)


def rows(path):
    with contextlib.closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT pull, arm, reward, net_reward, model, parameters FROM results ORDER BY pull").fetchall()


def as_results(saved):
    return [{"Arm": str(arm), "Reward": reward, "NetReward": net, "Pull": pull}
            for pull, arm, reward, net, _, _ in saved]


def copy_real_db(folder):
    """A copy of the real database, read through a read-only connection."""
    target = Path(folder) / "history.sqlite3"
    with contextlib.closing(sqlite3.connect(REAL_DB.as_uri() + "?mode=ro", uri=True)) as source, \
            contextlib.closing(sqlite3.connect(target)) as copy:
        source.backup(copy)
    return target


def fake_for(path, **kwargs):
    """A fake server that agrees with the database at `path`."""
    saved = rows(path)
    rates = [0.0] * 24
    for arm in range(24):
        rewards = [reward for _, a, reward, _, _, _ in saved if a == arm]
        rates[arm] = sum(rewards) / (100 * len(rewards))
    return FakeServer(len(saved), saved[-1][3], rates, **kwargs)


def run_main(server, **settings):
    """Run main.main() with these config.py values against `server`, capturing its output."""
    clock, out = Clock(), io.StringIO()
    server_pull._sessions.clear()
    patches = [
        mock.patch.object(server_pull, "_request", server.request),
        mock.patch.object(server_pull, "build_opener", no_network),
        mock.patch("bandit.client.time.monotonic", clock.monotonic),
        mock.patch("bandit.client.time.sleep", clock.sleep),
        mock.patch("bandit.runner.utc_now", lambda: datetime(2026, 11, 10, tzinfo=timezone.utc)),
        mock.patch.object(main, "getpass", lambda prompt: "check-password"),
        mock.patch.dict("os.environ", {"GP3_PASSWORD": ""}),
        mock.patch.multiple(config, **settings),
    ]
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(out))
        code = main.main()
    return code, out.getvalue()


def replay_matches(saved, start):
    """How many pulls from `start` on differ from UCBModel's choice given the pulls before them."""
    results = as_results(saved)
    model = UCBModel(main.exploration()).fit(results[:start])
    differ = 0
    for row in results[start:]:
        differ += model.select_arm() != int(row["Arm"])
        model.update(row)
    return differ


def check():
    before = hashlib.sha256(REAL_DB.read_bytes()).hexdigest()
    report("exploration from the multiplier", main.exploration() == 0.005,
           "UCB x{:g} gives UCBModel(exploration={!r})".format(config.UCB_MULTIPLIER, main.exploration()))

    with tempfile.TemporaryDirectory() as folder:
        db = copy_real_db(folder)
        start = len(rows(db))
        expected_first = UCBModel(main.exploration()).fit(as_results(rows(db))).select_arm()
        server = fake_for(db)
        goal = start + 960  # Each check aims 960 pulls past whatever the real database holds
        online = dict(DB_PATH=str(db), ONLINE=True, TARGET_TOTAL_PULLS=goal)

        # 1. Offline makes no requests and changes nothing.
        code, out = run_main(server, DB_PATH=str(db), ONLINE=False, TARGET_TOTAL_PULLS=goal, MAX_PULLS_THIS_RUN=1)
        report("offline run makes no requests", code == 0 and server.status_calls + server.pull_calls == 0
               and len(rows(db)) == start and "online it would be 1)" in out,
               "{} requests, {} pulls saved, next pull arm {}".format(
                   server.status_calls + server.pull_calls, len(rows(db)), expected_first))

        # 2. The 1-pull live test goes to UCB's choice and is saved as UCB with exploration 0.005.
        code, out = run_main(server, MAX_PULLS_THIS_RUN=1, **online)
        saved = rows(db)
        last = saved[-1]
        report("1-pull test goes to UCB's choice", code == 0 and len(saved) == start + 1
               and last[1] == expected_first and last[4] == "ucb" and '"exploration": 0.005' in last[5],
               "pull {} on arm {}, saved as model {!r} with {}".format(last[0], last[1], last[4], last[5]))

        # 3. A large run stops exactly at the target.
        code, out = run_main(server, MAX_PULLS_THIS_RUN=5000, **online)
        saved = rows(db)
        report("run stops at the target", code == 0 and len(saved) == goal and server.used == goal,
               "{:,} pulls saved, server at {:,}".format(len(saved), server.used))

        # 4. Every pull after the pilot is the arm UCBModel picks from the pulls before it.
        differ = replay_matches(saved, start)
        report("every choice matches UCBModel", differ == 0,
               "{} of {} pulls differ when replayed one at a time".format(differ, len(saved) - start))

        # 5. At the target, a rerun plans no pulls and sends nothing.
        calls = server.status_calls + server.pull_calls
        code, out = run_main(server, MAX_PULLS_THIS_RUN=5000, **online)
        report("rerun at the target makes no pulls", code == 0 and len(rows(db)) == goal
               and server.status_calls + server.pull_calls == calls,
               "{} new requests".format(server.status_calls + server.pull_calls - calls))

        # 6. Raising the target continues from the saved pulls.
        code, out = run_main(server, DB_PATH=str(db), ONLINE=True, TARGET_TOTAL_PULLS=goal + 50, MAX_PULLS_THIS_RUN=50)
        saved = rows(db)
        report("raising the target continues", code == 0 and len(saved) == goal + 50 and replay_matches(saved, start) == 0,
               "{:,} pulls saved; choices still match UCBModel".format(len(saved)))

    with tempfile.TemporaryDirectory() as folder:
        db = copy_real_db(folder)

        # 7. A lost response is retried with the same request, so it counts once.
        server = fake_for(db, lose_responses=1)
        code, out = run_main(server, DB_PATH=str(db), ONLINE=True, TARGET_TOTAL_PULLS=goal, MAX_PULLS_THIS_RUN=3)
        report("lost response counts once", code == 0 and len(rows(db)) == start + 3 and server.used == start + 3
               and "same request" in out,
               "{} pull requests sent for 3 pulls; server and database both at {}".format(
                   server.pull_calls, server.used))

        # 8. If the server has pulls the database doesn't, it stops before pulling.
        server = fake_for(db)
        server.used += 1
        code, out = run_main(server, DB_PATH=str(db), ONLINE=True, TARGET_TOTAL_PULLS=goal, MAX_PULLS_THIS_RUN=3)
        report("server ahead of database stops", code == 1 and server.pull_calls == 0
               and "the server has pulls this database does not" in out,
               "exit {}, {} pull requests".format(code, server.pull_calls))

        # 9. Bad settings stop before any request.
        server = fake_for(db)
        bad = [dict(UCB_MULTIPLIER=0), dict(UCB_MULTIPLIER=True), dict(TARGET_TOTAL_PULLS=float(goal)),
               dict(MAX_PULLS_THIS_RUN=-1), dict(ONLINE="yes")]
        codes = [run_main(server, **{"DB_PATH": str(db), "ONLINE": False, **settings})[0] for settings in bad]
        report("bad settings stop", codes == [1] * len(bad) and server.status_calls + server.pull_calls == 0,
               "{} of {} rejected, {} requests".format(codes.count(1), len(bad),
                                                      server.status_calls + server.pull_calls))

    after = hashlib.sha256(REAL_DB.read_bytes()).hexdigest()
    report("real database unchanged", before == after, str(REAL_DB))
    print("\n{}".format("All checks passed." if not FAILURES else "FAILED: " + ", ".join(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(check())
