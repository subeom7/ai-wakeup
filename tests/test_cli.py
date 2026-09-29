from __future__ import annotations
import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from ai_wakeup.cli import main
from ai_wakeup.store import Store


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.home=str(Path(self.tmp.name)/"state")
        self.session=str(uuid.uuid4())

    def tearDown(self):
        self.tmp.cleanup()

    def call(self,*args):
        output,errors=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(errors):
            code=main(["--home",self.home,*args])
        return code,output.getvalue(),errors.getvalue()

    def schedule(self,*extra):
        return self.call("schedule","codex","--session",self.session,"--cwd",self.tmp.name,
                         "--after","1h","--executable",sys.executable,*extra)

    def test_empty_status(self):
        code,out,_=self.call("status","--json")
        self.assertEqual(code,0)
        data=json.loads(out)
        self.assertFalse(data["worker_lock_held"])
        self.assertEqual(data["jobs"],[])

    def test_schedule_does_not_start_worker(self):
        code,out,err=self.schedule("--json")
        self.assertEqual(code,0,err)
        data=json.loads(out)
        self.assertEqual(data["status"],"queued")
        self.assertEqual(data["session_id"],self.session)
        self.assertFalse(json.loads(self.call("status","--json")[1])["worker_lock_held"])

    def test_preview_has_no_execution_side_effects(self):
        self.schedule()
        store=Store(Path(self.home))
        before=store.list_jobs()
        code,out,err=self.call("preview","--json")
        self.assertEqual(code,0,err)
        preview=json.loads(out)[0]
        self.assertFalse(preview["shell"])
        self.assertFalse(preview["session_and_auth_verified"])
        self.assertNotIn("prompt",preview)
        self.assertEqual(before,store.list_jobs())
        self.assertEqual(list((Path(self.home)/"logs").iterdir()),[])

    def test_prompt_file_unicode(self):
        p=Path(self.tmp.name)/"prompt.txt"
        p.write_text("한글 지시문",encoding="utf-8-sig")
        self.assertEqual(self.schedule("--prompt-file",str(p))[0],0)
        result=json.loads(self.call("preview","--show-prompt","--json")[1])
        self.assertEqual(result[0]["prompt"],"한글 지시문")

    def test_blank_prompt_rejected(self):
        self.assertEqual(self.schedule("--prompt","")[0],2)

    def test_duplicate_schedule_rejected(self):
        self.assertEqual(self.schedule()[0],0)
        self.assertEqual(self.schedule()[0],2)

    def test_invalid_uuid_rejected(self):
        self.session="--last"
        code,_,_=self.call("schedule","codex","--session=not-a-uuid","--cwd",self.tmp.name,
                          "--after","1h","--executable",sys.executable)
        self.assertEqual(code,2)

    def test_cancel_short_job_id(self):
        job=json.loads(self.schedule("--json")[1])
        self.assertEqual(self.call("cancel",job["id"][:8])[0],0)
        status=json.loads(self.call("status","--json")[1])["jobs"][0]
        self.assertEqual(status["status"],"cancelled")

    def test_logs_before_execution(self):
        job=json.loads(self.schedule("--json")[1])
        code,out,_=self.call("logs",job["id"])
        self.assertEqual(code,0)
        self.assertIn("No attempt",out)

    def test_stop_when_not_running(self):
        code,out,_=self.call("stop")
        self.assertEqual(code,0)
        self.assertIn("No worker",out)

    def test_unsafe_naive_absolute_time(self):
        code,_,_=self.call("schedule","codex","--session",self.session,"--cwd",self.tmp.name,
                          "--at","2099-01-01T01:00:00","--executable",sys.executable)
        self.assertEqual(code,2)

    def test_unknown_review_resolution_rejected(self):
        job=json.loads(self.schedule("--json")[1])
        self.assertEqual(self.call("resolve",job["id"],"--acknowledge-stopped")[0],2)
