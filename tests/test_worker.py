from __future__ import annotations
import contextlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

import ai_wakeup
from ai_wakeup.core import JobSpec
from ai_wakeup.events import Outcome
from ai_wakeup.store import Store
from ai_wakeup.worker import AlreadyRunning, Worker, WorkerLock, is_running, next_retry

FIXTURE = str(Path(ai_wakeup.__file__).with_name("_demo_agent.py"))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.project=self.root/"project & 한글 space"
        self.project.mkdir()
        self.store=Store(self.root/"state")

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, provider="codex", scenario="success", **changes):
        spec=JobSpec(provider,str(uuid.uuid4()),str(self.project), '계속해. "quotes" & $(not-a-shell)',
                     (sys.executable,FIXTURE,provider,scenario))
        spec=replace(spec,**changes)
        return self.store.add(spec,time.time()-1,time.time()+3600,3)

    def run_once(self):
        with contextlib.redirect_stdout(io.StringIO()):
            Worker(self.store).run(once=True)

    def test_real_child_codex_success(self):
        job=self.job()
        self.run_once()
        updated=self.store.get(job["id"])
        self.assertEqual(updated["status"],"completed")
        self.assertEqual(updated["attempts"],1)
        self.assertEqual(updated["exit_code"],0)
        log=self.store.home/"logs"/(updated["log_base"]+".stdout.jsonl")
        events=[json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        item=next(e["item"] for e in events if e["type"]=="item.completed")
        # macOS may spell the same temporary directory as /var or /private/var.
        self.assertTrue(Path(item["cwd"]).samefile(self.project))
        self.assertEqual(item["stdin"].strip(),Store.spec(job).prompt)

    def test_real_child_claude_success(self):
        job=self.job("claude")
        self.run_once()
        self.assertEqual(self.store.get(job["id"])["status"],"completed")

    def test_recognized_rate_retry(self):
        job=self.job(scenario="rate_limit")
        before=time.time()
        self.run_once()
        updated=self.store.get(job["id"])
        self.assertEqual(updated["status"],"retry_wait")
        self.assertGreaterEqual(updated["due_at"],before+900)
        self.assertIsNone(self.store.claim())

    def test_claude_rate_retry(self):
        job=self.job("claude","rate_limit")
        self.run_once()
        self.assertEqual(self.store.get(job["id"])["status"],"retry_wait")

    def test_unknown_failure_not_retried(self):
        job=self.job(scenario="unknown_failure")
        self.run_once()
        self.assertEqual(self.store.get(job["id"])["status"],"failed")

    def test_unknown_zero_exit_not_marked_success(self):
        job=self.job(scenario="silent_success")
        self.run_once()
        self.assertEqual(self.store.get(job["id"])["status"],"needs_review")

    def test_wrong_session_not_marked_success(self):
        job=self.job(scenario="wrong_session")
        self.run_once()
        self.assertEqual(self.store.get(job["id"])["status"],"needs_review")

    def test_permission_denial_stops(self):
        job=self.job("claude","denied")
        self.run_once()
        self.assertEqual(self.store.get(job["id"])["status"],"needs_review")

    def test_timeout_no_retry(self):
        job=self.job(scenario="sleep",timeout_seconds=1)
        self.run_once()
        updated=self.store.get(job["id"])
        self.assertEqual(updated["status"],"needs_review")
        self.assertIn("timeout",updated["last_error"])

    def test_log_guard_no_retry(self):
        job=self.job(scenario="flood",max_log_bytes=1024)
        self.run_once()
        updated=self.store.get(job["id"])
        self.assertEqual(updated["status"],"needs_review")
        self.assertIn("Log size",updated["last_error"])

    def test_cancellation_reaches_running_child(self):
        job=self.job(scenario="sleep")
        worker=Worker(self.store)
        errors=[]
        def run():
            try: worker.run(once=True)
            except Exception as exc: errors.append(exc)
        with contextlib.redirect_stdout(io.StringIO()):
            thread=threading.Thread(target=run)
            thread.start()
            try:
                deadline=time.monotonic()+10
                while not self.store.get(job["id"])["pid"] and time.monotonic()<deadline:
                    time.sleep(.05)
                self.assertIsNotNone(self.store.get(job["id"])["pid"])
                self.store.cancel(job["id"])
            finally:
                worker.stop_event.set() if errors else None
                thread.join(10)
                if thread.is_alive():
                    worker.stop_event.set()
                    thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertEqual(self.store.get(job["id"])["status"],"cancelled")

    def test_only_one_worker_lock(self):
        self.assertFalse(is_running(self.store.home))
        with WorkerLock(self.store.home):
            self.assertTrue(is_running(self.store.home))
            with self.assertRaises(AlreadyRunning):
                with WorkerLock(self.store.home): pass
        self.assertFalse(is_running(self.store.home))

    def test_restart_keeps_crashed_job_for_review(self):
        job=self.job()
        self.store.claim()
        self.run_once()
        self.assertEqual(self.store.get(job["id"])["status"],"needs_review")
        self.assertEqual(self.store.get(job["id"])["attempts"],1)

    def test_retry_budget_and_backoff(self):
        job=self.job()
        job.update(attempts=1,expires_at=100000)
        self.assertEqual(next_retry(job,Outcome("rate_limit","limited"),0),900)
        job["attempts"]=2
        self.assertEqual(next_retry(job,Outcome("rate_limit","limited"),0),1800)
        job["attempts"]=3
        self.assertIsNone(next_retry(job,Outcome("rate_limit","limited"),0))

    def test_retry_respects_provider_hint_and_expiry(self):
        job=self.job()
        job.update(attempts=1,expires_at=20000)
        self.assertEqual(next_retry(job,Outcome("rate_limit","limited",3600),100),3705)
        job["expires_at"]=3700
        self.assertIsNone(next_retry(job,Outcome("rate_limit","limited",3600),100))

    def test_not_a_rate_error_no_retry(self):
        job=self.job()
        job["attempts"]=1
        self.assertIsNone(next_retry(job,Outcome("failure","login expired"),0))
