"""Append-only results and transactional recovery state in one local database."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .common import ARMS, MAX_PULLS, integer, normalize_result, server_address, timestamp


@contextmanager
def driver_lock(path):
    """One driver per resolved database on macOS/Linux/Windows."""
    try:
        import fcntl
    except ImportError:
        fcntl = None
        import msvcrt

    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+b") as handle:
        if fcntl is None:
            handle.seek(0, 2)
            if not handle.tell():
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("Another driver is using this database") from None
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.execute("PRAGMA cache_size = -4096")
        self.connection.execute("PRAGMA temp_store = FILE")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS results (
                pull INTEGER PRIMARY KEY, arm INTEGER NOT NULL, reward INTEGER NOT NULL,
                net_reward INTEGER NOT NULL, saved_at TEXT NOT NULL,
                model TEXT NOT NULL, parameters TEXT NOT NULL, request_id TEXT);
            CREATE TABLE IF NOT EXISTS pending (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tuning_decisions (
                id INTEGER PRIMARY KEY, at_pull INTEGER NOT NULL, payload TEXT NOT NULL);
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.connection.close()

    @property
    def identity(self):
        row = self.connection.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
        return json.loads(row[0]) if row else None

    def bind(self, username, server_url):
        if not isinstance(username, str) or not username.strip():
            raise ValueError("A group username is required")
        identity = {"username": username, "server_url": server_address(server_url)}
        with self.connection:
            current = self.identity
            if current is not None and current != identity:
                raise ValueError("This database belongs to another group or server")
            self.connection.execute("INSERT OR IGNORE INTO metadata VALUES ('identity', ?)",
                                    (json.dumps(identity),))

    @property
    def pending(self):
        row = self.connection.execute("SELECT payload FROM pending WHERE singleton=1").fetchone()
        return json.loads(row[0]) if row else None

    @property
    def last_pull(self):
        return self.connection.execute("SELECT MAX(pull) FROM results").fetchone()[0]

    def results(self):
        for row in self.connection.execute("SELECT * FROM results ORDER BY pull"):
            yield {"Arm": str(row["arm"]), "Reward": row["reward"],
                   "NetReward": row["net_reward"], "Pull": row["pull"]}

    def aggregate(self):
        """At most 24 rows; SQLite handles history scanning with a bounded cache."""
        return [dict(row) for row in self.connection.execute(
            "SELECT arm, COUNT(*) AS pulls, SUM(reward) AS signups FROM results GROUP BY arm")]

    def tuning_state(self):
        row = self.connection.execute("SELECT value FROM metadata WHERE key='tuning_state'").fetchone()
        return json.loads(row[0]) if row else None

    def record_tuning(self, decision):
        payload = json.dumps(decision, allow_nan=False, separators=(',', ':'))
        with self.connection:
            if self.pending is not None:
                raise RuntimeError('Cannot change policy with an unresolved request')
            self.connection.execute('INSERT INTO tuning_decisions(at_pull,payload) VALUES (?,?)',
                                    (decision['at_pull'], payload))
            self.connection.execute("INSERT OR REPLACE INTO metadata VALUES ('tuning_state', ?)",
                                    (payload,))

    def _insert(self, result, model="imported", parameters=None, request_id=None):
        if self.identity is None:
            raise ValueError("Bind the group and server before saving real results")
        row = normalize_result(result)
        existing = self.connection.execute("SELECT * FROM results WHERE pull=?", (row["Pull"],)).fetchone()
        if existing:
            if (existing["arm"], existing["reward"], existing["net_reward"]) != (
                    int(row["Arm"]), row["Reward"], row["NetReward"]):
                raise ValueError("Conflicting results for the same pull index")
            return False
        self.connection.execute("INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (row["Pull"], int(row["Arm"]), row["Reward"], row["NetReward"],
                                 timestamp(), model, json.dumps(parameters or {}, allow_nan=False), request_id))
        return True

    def append_result(self, result):
        return bool(self.import_results([result]))

    def import_results(self, results):
        with self.connection:
            if self.pending is not None:
                raise RuntimeError("Resolve the pending online request before importing")
            return sum(self._insert(result) for result in results)

    def prepare(self, *, arm, expected_pull, model, parameters):
        integer(arm, "arm", maximum=ARMS - 1)
        integer(expected_pull, "expected_pull", maximum=MAX_PULLS - 1)
        if self.identity is None:
            raise ValueError("Bind the group before preparing requests")
        payload = {"arm": arm, "expected_pull": expected_pull, "request_id": str(uuid.uuid4()),
                   "model": model, "parameters": parameters, "created_at": timestamp()}
        with self.connection:
            if self.pending is not None:
                raise RuntimeError("Resolve the pending request first")
            self.connection.execute("INSERT INTO pending VALUES (1, ?)",
                                    (json.dumps(payload, allow_nan=False),))
        return payload

    def complete(self, result):
        row = normalize_result(result)
        with self.connection:
            request = self.pending
            if request is None or (int(row["Arm"]), row["Pull"]) != (
                    request["arm"], request["expected_pull"]):
                raise ValueError("Response does not match the pending request")
            previous = self.connection.execute('SELECT net_reward FROM results WHERE pull=?',
                                               (row['Pull']-1,)).fetchone()
            if (previous is not None and row['NetReward'] != previous[0]+row['Reward']) or (
                    row['Pull'] == 0 and row['NetReward'] != row['Reward']):
                raise ValueError('Response cumulative reward does not match saved history')
            inserted = self._insert(row, request["model"], request["parameters"], request["request_id"])
            self.connection.execute("DELETE FROM pending WHERE singleton=1")
        return inserted

    def _cancel_unsent(self, request_id):
        """Runner-only: caller must prove HTTP transmission has never started."""
        with self.connection:
            request = self.pending
            if request is None or request["request_id"] != request_id:
                raise RuntimeError("Cannot cancel a different pending request")
            self.connection.execute("DELETE FROM pending WHERE singleton=1")

    def export_jsonl(self, target):
        target = Path(target).expanduser().resolve()
        if target == self.path or target == self.path.with_suffix(self.path.suffix + ".lock"):
            raise ValueError("Export must not overwrite the database or lock")
        count = 0
        # Exclusive creation protects existing exports/logs from accidental replacement.
        with target.open("x", encoding="utf-8") as handle:
            for row in self.results():
                handle.write(json.dumps(row) + "\n")
                count += 1
        return count
