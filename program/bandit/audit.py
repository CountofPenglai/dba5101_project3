"""Human-readable append-only JSONL events; callers supply whitelisted fields."""

import json
import os
from pathlib import Path

from .common import timestamp


class OnlineLog:
    def __init__(self, path, run_id):
        self.path = Path(path).expanduser().resolve()
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a", encoding="utf-8")

    def write(self, event, **fields):
        row = {"timestamp": timestamp(), "run_id": self.run_id, "event": event, **fields}
        self.handle.write(json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.handle.close()
