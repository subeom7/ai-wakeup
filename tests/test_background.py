"""Lifecycle integration with a detached LOCAL worker; never a real AI provider."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ai_wakeup.store import Store
from ai_wakeup.worker import is_running, request_stop

ROOT=Path(__file__).resolve().parents[1]


class BackgroundTests(unittest.TestCase):
    def test_detached_worker_outlives_launcher_and_stops_cooperatively(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)/"state"
            env=os.environ.copy()
            env["PYTHONUTF8"]="1"
            def call(*args):
                return subprocess.run([sys.executable,"-m","ai_wakeup","--home",str(home),*args],
                                      cwd=ROOT,env=env,capture_output=True,text=True,encoding="utf-8",timeout=15)
            store=Store(home)
            try:
                started=call("start")
                self.assertEqual(started.returncode,0,started.stderr)
                # The launch command has exited, while the detached worker remains alive.
                first=json.loads(call("status","--json").stdout)
                self.assertTrue(first["worker_lock_held"])
                again=call("start")
                self.assertEqual(again.returncode,0,again.stderr)
                self.assertIn("already running",again.stdout)
                second=json.loads(call("status","--json").stdout)
                self.assertEqual(first["worker"]["pid"],second["worker"]["pid"])
                rejected=call("worker","--once")
                self.assertEqual(rejected.returncode,2)
                self.assertIn("lock",rejected.stderr)
                stopped=call("stop")
                self.assertEqual(stopped.returncode,0,stopped.stderr)
            finally:
                request_stop(store)
                deadline=time.monotonic()+15
                while is_running(home) and time.monotonic()<deadline:
                    time.sleep(.1)
                self.assertFalse(is_running(home),"Detached test worker failed to stop")
                # Allow process-level stdout/log handles to close on Windows.
                time.sleep(.5)
