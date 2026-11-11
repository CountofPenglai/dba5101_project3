"""Focused hard-exit and recovery checks; no real HTTP or real experiment data."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import server_pull
from bandit import run_experiment
from bandit.storage import HistoryStore
from test_runner import Clock, FakeServer


class CrashSafetyTests(unittest.TestCase):
    def test_hard_exit_after_remote_commit_recovers_exact_original_uuid_once(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'history.sqlite3'
            receipt = Path(folder)/'remote.json'
            script = '''
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from bandit import run_experiment
def request(user,password,path,timeout,data=None):
 if path=='/v1/status':
  return 200,{'PullsUsed':0,'NetReward':0,'MaxPulls':1000000,'Open':True}
 result={'Arm':str(data['arm']),'Reward':20,'NetReward':20,'Pull':0}
 with open(sys.argv[2],'w') as f:
  json.dump({'request':data,'result':result},f);f.flush();os.fsync(f.fileno())
 os._exit(99)
with patch('server_pull._request',request),patch('bandit.runner.utc_now',lambda:datetime(2026,11,1,tzinfo=timezone.utc)):
 run_experiment('ucb',1,online=True,db_path=sys.argv[1],username='fake',password='fake')
'''
            child = subprocess.run([sys.executable, '-c', script, str(db), str(receipt)],
                                   cwd=Path(__file__).resolve().parents[1],
                                   capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 99, child.stderr)
            remote = json.loads(receipt.read_text())
            with HistoryStore(db) as store:
                self.assertEqual(store.pending['request_id'], remote['request']['request_id'])
                self.assertEqual(store.aggregate(), [])
            clock = Clock()
            server = FakeServer(clock)
            server.used, server.total = 1, 20
            server.receipts[remote['request']['request_id']] = (remote['request'], remote['result'])
            server_pull._sessions.clear()
            with patch('server_pull._request', server.request), \
                    patch('bandit.client.time.monotonic', clock.monotonic), \
                    patch('bandit.client.time.sleep', clock.sleep), \
                    patch('bandit.runner.utc_now', lambda: datetime(2026,11,1,tzinfo=timezone.utc)):
                summary = run_experiment('ucb', 1, online=True, db_path=db, username='fake', password='fake')
            self.assertEqual(summary['completed_pulls'], 1)
            self.assertEqual(server.used, 1)
            self.assertEqual(len(server.calls), 1)
            self.assertIsNone(summary['pending_request'])


if __name__ == '__main__':
    unittest.main()
