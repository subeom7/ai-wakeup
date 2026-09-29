"""SQLite ledger. Queues survive restart; interrupted executions never auto-replay."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from .core import ACTIVE_STATES, JobSpec, WakeupError, deserialize_spec, private_directory, serialize_spec

SCHEMA_VERSION = 1
STATES = (*ACTIVE_STATES, "completed", "failed", "cancelled", "expired")


class Store:
    def __init__(self, home: Path):
        self.home = home
        private_directory(home)
        private_directory(home / "logs")
        self.path = home / "state.sqlite3"
        with closing(self.connect()) as con:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise WakeupError(f"Unsupported state schema {version}; do not downgrade this installation.")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, session_id TEXT NOT NULL, cwd_key TEXT NOT NULL,
                    spec TEXT NOT NULL, status TEXT NOT NULL, due_at REAL NOT NULL,
                    expires_at REAL NOT NULL, max_attempts INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    pid INTEGER, exit_code INTEGER, last_error TEXT, log_base TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_session
                    ON jobs(provider, session_id)
                    WHERE status IN ('queued','retry_wait','running','needs_review');
                CREATE INDEX IF NOT EXISTS due_jobs ON jobs(status, due_at);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if os.name != "nt":
            self.path.chmod(0o600)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def add(self, spec: JobSpec, due_at: float, expires_at: float, max_attempts: int = 3,
            *, now: float | None = None) -> dict[str, Any]:
        spec.validate()
        if not all(math.isfinite(v) for v in (due_at, expires_at)) or expires_at <= due_at:
            raise WakeupError("Expiry must be later than the scheduled time.")
        if not 1 <= max_attempts <= 10:
            raise WakeupError("Max attempts must be between 1 and 10 (including the first run).")
        now = time.time() if now is None else now
        job_id = str(uuid.uuid4())
        try:
            with closing(self.connect()) as con:
                con.execute("""INSERT INTO jobs
                    (id,provider,session_id,cwd_key,spec,status,due_at,expires_at,max_attempts,created_at,updated_at)
                    VALUES (?,?,?,?,?,'queued',?,?,?,?,?)""",
                    (job_id, spec.provider, spec.session_id, os.path.normcase(str(Path(spec.cwd).resolve())), serialize_spec(spec), due_at, expires_at, max_attempts, now, now))
        except sqlite3.IntegrityError as exc:
            raise WakeupError("This provider/session already has an active job. Cancel or resolve it before scheduling another.") from exc
        return self.get(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as con:
            return [dict(row) for row in con.execute("SELECT * FROM jobs ORDER BY created_at DESC, id")]

    def get(self, job_id: str) -> dict[str, Any]:
        with closing(self.connect()) as con:
            rows = con.execute("SELECT * FROM jobs WHERE id=? OR substr(id,1,?)=?",
                               (job_id, len(job_id), job_id)).fetchall()
        if len(rows) != 1:
            raise WakeupError("Job ID not found or ambiguous; use the full ID from status.")
        return dict(rows[0])

    def claim(self, now: float | None = None) -> dict[str, Any] | None:
        now = time.time() if now is None else now
        with closing(self.connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("""UPDATE jobs SET status='expired', updated_at=?,
                last_error='The scheduling window expired; no process was started.'
                WHERE status IN ('queued','retry_wait') AND expires_at<=?""", (now, now))
            row = con.execute("""SELECT j.* FROM jobs j WHERE j.status IN ('queued','retry_wait')
                AND j.due_at<=? AND j.expires_at>?
                AND NOT EXISTS (SELECT 1 FROM jobs b WHERE b.cwd_key=j.cwd_key AND b.status IN ('running','needs_review'))
                ORDER BY j.due_at, j.created_at LIMIT 1""", (now, now)).fetchone()
            if row is None:
                con.commit()
                return None
            con.execute("""UPDATE jobs SET status='running', attempts=attempts+1,
                updated_at=?, pid=NULL, exit_code=NULL WHERE id=?""", (now, row["id"]))
            con.commit()
        return self.get(row["id"])

    def update(self, job_id: str, **values: Any) -> None:
        allowed = {"status", "due_at", "pid", "exit_code", "last_error", "log_base", "cancel_requested"}
        if not values or set(values) - allowed:
            raise WakeupError("Invalid ledger update.")
        if "status" in values and values["status"] not in STATES:
            raise WakeupError("Invalid job status.")
        values["updated_at"] = time.time()
        sql = ",".join(f"{key}=?" for key in values)
        with closing(self.connect()) as con:
            con.execute(f"UPDATE jobs SET {sql} WHERE id=?", (*values.values(), job_id))

    def cancel(self, job_id: str) -> str:
        job_id = self.get(job_id)["id"]
        with closing(self.connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            status = row["status"]
            if status == "needs_review":
                raise WakeupError("Inspect the previous process/logs first, then use resolve --acknowledge-stopped.")
            if status == "running":
                con.execute("UPDATE jobs SET cancel_requested=1,updated_at=? WHERE id=?", (time.time(), job_id))
                result = "Cancellation requested; the worker must confirm process termination."
            elif status in ("queued", "retry_wait"):
                con.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=?", (time.time(), job_id))
                result = "Cancelled; no scheduled process will be started."
            else:
                result = f"Already {status}; unchanged."
            con.commit()
        return result

    def recover_interrupted(self) -> int:
        """Only call while holding the exclusive worker lock."""
        with closing(self.connect()) as con:
            cur = con.execute("""UPDATE jobs SET status='needs_review',updated_at=?,
                last_error='The previous worker exited during execution. A child process may still exist. Inspect it before resolving; never auto-replay.'
                WHERE status='running'""", (time.time(),))
            return cur.rowcount

    def resolve(self, job_id: str) -> None:
        job = self.get(job_id)
        with closing(self.connect()) as con:
            cur = con.execute("""UPDATE jobs SET status='cancelled',updated_at=?,
                last_error='User acknowledged that the previous process stopped; job closed without replay.'
                WHERE id=? AND status='needs_review'""", (time.time(), job["id"]))
            if cur.rowcount != 1:
                raise WakeupError("Only needs_review jobs can be resolved.")

    def set_meta(self, key: str, value: Any) -> None:
        with closing(self.connect()) as con:
            con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value)))

    def meta(self, key: str, default: Any = None) -> Any:
        with closing(self.connect()) as con:
            row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    @staticmethod
    def spec(job: dict[str, Any]) -> JobSpec:
        return deserialize_spec(job["spec"])

    def finish(self, job_id: str, status: str, detail: str, *, exit_code: int | None = None,
               due_at: float | None = None, keep_pid: bool = False) -> None:
        """Finalize atomically with cancellation: never overwrite a late cancel with a retry."""
        if status not in STATES or status == "running":
            raise WakeupError("Invalid final state.")
        with closing(self.connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["status"] != "running":
                raise WakeupError("Only a claimed running job can be finalized.")
            if row["cancel_requested"] and status != "needs_review":
                status, detail = "cancelled", "Cancellation confirmed after the child process stopped."
            con.execute("""UPDATE jobs SET status=?, last_error=?, exit_code=?,
                due_at=?, pid=?, updated_at=? WHERE id=?""",
                (status, detail[:3000], exit_code, due_at if due_at is not None else row["due_at"],
                 row["pid"] if keep_pid else None, time.time(), job_id))
            con.commit()
