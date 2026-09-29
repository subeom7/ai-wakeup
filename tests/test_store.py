import sys
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from ai_wakeup.core import JobSpec, WakeupError
from ai_wakeup.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.home=Path(self.tmp.name)/"state"
        self.store=Store(self.home)
        self.spec=JobSpec("codex",str(uuid.uuid4()),self.tmp.name,"continue",(sys.executable,))

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, **kw):
        return self.store.add(self.spec,kw.get("due",100),kw.get("expires",200),kw.get("attempts",3),now=90)

    def test_persistence(self):
        job=self.add()
        self.assertEqual(Store(self.home).get(job["id"])["status"],"queued")

    def test_duplicate_session_blocked(self):
        self.add()
        with self.assertRaises(WakeupError): self.add()

    def test_not_due(self):
        self.add()
        self.assertIsNone(self.store.claim(99))

    def test_claim_once(self):
        self.add()
        self.assertEqual(self.store.claim(100)["attempts"],1)
        self.assertIsNone(self.store.claim(100))

    def test_concurrent_claims(self):
        self.add()
        with ThreadPoolExecutor(max_workers=5) as pool:
            results=list(pool.map(lambda _:self.store.claim(100),range(5)))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_expiration(self):
        job=self.add()
        self.assertIsNone(self.store.claim(201))
        self.assertEqual(self.store.get(job["id"])["status"],"expired")

    def test_cancel_before_run(self):
        job=self.add()
        self.store.cancel(job["id"])
        self.assertIsNone(self.store.claim(150))
        self.assertEqual(self.store.get(job["id"])["status"],"cancelled")

    def test_cancel_running_sets_request(self):
        job=self.add()
        self.store.claim(100)
        self.store.cancel(job["id"])
        row=self.store.get(job["id"])
        self.assertEqual((row["status"],row["cancel_requested"]),("running",1))

    def test_cancel_wins_over_retry_race(self):
        job=self.add()
        self.store.claim(100)
        self.store.cancel(job["id"])
        self.store.finish(job["id"],"retry_wait","rate",due_at=180)
        self.assertEqual(self.store.get(job["id"])["status"],"cancelled")

    def test_interrupted_never_replayed(self):
        job=self.add()
        self.store.claim(100)
        self.assertEqual(self.store.recover_interrupted(),1)
        self.assertEqual(self.store.get(job["id"])["status"],"needs_review")
        self.assertIsNone(self.store.claim(150))
        with self.assertRaises(WakeupError): self.add()

    def test_review_blocks_same_workspace_other_session(self):
        first=self.add()
        self.store.claim(100)
        self.store.recover_interrupted()
        other=replace(self.spec,session_id=str(uuid.uuid4()))
        self.store.add(other,100,200,now=91)
        self.assertIsNone(self.store.claim(150))
        self.store.resolve(first["id"])
        self.assertIsNotNone(self.store.claim(150))

    def test_explicit_resolve_does_not_restart(self):
        job=self.add()
        self.store.claim(100)
        self.store.recover_interrupted()
        with self.assertRaises(WakeupError): self.store.cancel(job["id"])
        self.store.resolve(job["id"])
        self.assertEqual(self.store.get(job["id"])["status"],"cancelled")
        self.assertIsNone(self.store.claim(150))

    def test_retry_budget_validation(self):
        with self.assertRaises(WakeupError): self.add(attempts=0)
        with self.assertRaises(WakeupError): self.add(attempts=11)

    def test_invalid_expiry(self):
        with self.assertRaises(WakeupError): self.add(due=200,expires=100)

    def test_metadata(self):
        self.store.set_meta("example",{"test":True})
        self.assertEqual(self.store.meta("example"),{"test":True})

    def test_schema_newer_is_rejected(self):
        # sqlite3 context managers end transactions but do not close handles.
        with closing(self.store.connect()) as con:
            con.execute("PRAGMA user_version=999")
        with self.assertRaises(WakeupError): Store(self.home)
