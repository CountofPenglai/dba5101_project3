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
        # A killed writer may leave half a JSON object. Preserve it as an invalid
        # line rather than concatenating it with (and losing) the next good event.
        if self.path.exists() and self.path.stat().st_size:
            with self.path.open('rb+') as previous:
                previous.seek(-1, os.SEEK_END)
                if previous.read(1) != b'\n':
                    previous.seek(0, os.SEEK_END)
                    previous.write(b'\n')
                    previous.flush()
                    os.fsync(previous.fileno())
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


def tail_lines(path, count, max_bytes=2_000_000):
    """Read a bounded suffix, not a multi-gigabyte log from its beginning."""
    with Path(path).open('rb') as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        chunks, length, lines = [], 0, 0
        while end and length < max_bytes and lines <= count:
            size = min(8192, end, max_bytes - length)
            end -= size
            handle.seek(end)
            chunk = handle.read(size)
            chunks.append(chunk)
            length += size
            lines += chunk.count(b'\n')
        data = b''.join(reversed(chunks))
        if end:
            data = data.partition(b'\n')[2]
        return data.decode('utf-8', errors='replace').splitlines()[-count:]
