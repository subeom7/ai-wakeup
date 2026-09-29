"""Foreground/background worker with an OS lock and bounded child execution."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from .core import WakeupError, build_command, time_label
from .events import Outcome, classify_file
from .store import Store


class AlreadyRunning(WakeupError):
    pass


class WorkerLock:
    """Kernel-released lock; no stale PID-file deletion and no PID-based killing."""
    def __init__(self, home: Path):
        self.path = home / "worker.lock"
        self.file: BinaryIO | None = None

    def __enter__(self) -> "WorkerLock":
        self.file = self.path.open("a+b")
        if self.file.seek(0, os.SEEK_END) == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise AlreadyRunning("A worker already holds this data directory's lock.") from exc
        return self

    def __exit__(self, *_: Any) -> None:
        if self.file is not None:
            # Closing the handle releases flock / Windows byte-range lock.
            self.file.close()
            self.file = None


def is_running(home: Path) -> bool:
    try:
        with WorkerLock(home):
            return False
    except AlreadyRunning:
        return True


def private_file(path: Path, *, exclusive: bool = True) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_APPEND)
    return os.fdopen(os.open(path, flags, 0o600), "wb" if exclusive else "ab")


def stop_child(process: subprocess.Popen[bytes]) -> bool:
    """Best-effort termination of the child tree we created; never an arbitrary stored PID."""
    if process.poll() is not None:
        return True
    try:
        if os.name == "nt":
            killer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            subprocess.run([str(killer), "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return process.poll() is not None
    return process.poll() is not None


def next_retry(job: dict[str, Any], outcome: Outcome, now: float) -> float | None:
    if outcome.kind != "rate_limit" or job["attempts"] >= job["max_attempts"]:
        return None
    spec = Store.spec(job)
    delay = min(spec.retry_seconds * (2 ** (job["attempts"] - 1)), 86400)
    if outcome.retry_after is not None:
        delay = max(delay, outcome.retry_after + 5)
    due = now + delay
    return due if due < job["expires_at"] else None


class Worker:
    def __init__(self, store: Store, *, poll_seconds: float = 1):
        self.store = store
        self.poll_seconds = poll_seconds
        self.worker_id = str(uuid.uuid4())
        self.stop_event = threading.Event()
        self.current_job: str | None = None
        self.started_at = time.time()

    def heartbeat(self, state: str = "running") -> None:
        self.store.set_meta("worker", {
            "id": self.worker_id, "pid": os.getpid(), "state": state,
            "started_at": self.started_at, "heartbeat_at": time.time(),
            "current_job": self.current_job,
        })

    def should_stop(self) -> bool:
        return self.stop_event.is_set() or self.store.meta("stop_requested") == self.worker_id

    def log(self, message: str) -> None:
        print(f"{time_label(time.time())} {message}", flush=True)

    def run(self, *, once: bool = False) -> int:
        if not 0.1 <= self.poll_seconds <= 60:
            raise WakeupError("Poll interval must be between 0.1 and 60 seconds.")
        with WorkerLock(self.store.home):
            recovered = self.store.recover_interrupted()
            self.heartbeat()
            self.log(f"Worker ready; {recovered} interrupted job(s) require review.")
            previous_handlers = {}
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGINT, signal.SIGTERM):
                    previous_handlers[sig] = signal.signal(sig, lambda *_: self.stop_event.set())
            try:
                while not self.should_stop():
                    self.heartbeat()
                    job = self.store.claim()
                    if job is not None:
                        self.current_job = job["id"]
                        self.heartbeat()
                        self.execute(job)
                        self.current_job = None
                    if once:
                        break
                    self.stop_event.wait(self.poll_seconds)
            finally:
                self.current_job = None
                self.heartbeat("stopped")
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)
                self.log("Worker stopped. Pending schedules remain saved.")
        return 0

    def execute(self, job: dict[str, Any]) -> None:
        try:
            self._execute(job)
        except Exception as exc:
            # _execute always cleans up its child in finally. Never blindly re-run.
            if self.store.get(job["id"])["status"] == "running":
                self.store.finish(job["id"], "needs_review", f"Worker could not safely complete the attempt: {type(exc).__name__}: {exc}", keep_pid=True)
            self.log(f"{job['id'][:8]} needs_review (internal/execution error)")

    def _execute(self, job: dict[str, Any]) -> None:
        spec = self.store.spec(job)
        if not Path(spec.cwd).is_dir():
            self.store.finish(job["id"], "failed", "Project directory no longer exists; no process started.")
            return
        if self.should_stop() or self.store.get(job["id"])["cancel_requested"]:
            self.store.finish(job["id"], "cancelled" if not self.should_stop() else "needs_review", "Stopped before launching the CLI.")
            return
        command = build_command(spec)
        stem = f"{job['id']}-{job['attempts']}"
        log_dir = self.store.home / "logs"
        out_path, err_path = log_dir / f"{stem}.stdout.jsonl", log_dir / f"{stem}.stderr.log"
        self.store.update(job["id"], log_base=stem)
        manifest = {"job_id": job["id"], "session_id": spec.session_id, "provider": spec.provider,
                    "cwd": spec.cwd, "argv": command, "started_at": time_label(time.time()),
                    "prompt": "Supplied on stdin; stored only in local state DB, not this manifest."}
        with private_file(log_dir / f"{stem}.meta.json") as stream:
            stream.write(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        self.log(f"{job['id'][:8]} starting {spec.provider}; attempt {job['attempts']}/{job['max_attempts']}")
        reason: str | None = None
        process: subprocess.Popen[bytes] | None = None
        safely_stopped = True
        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["AI_WAKEUP_JOB_ID"] = job["id"]
        # Authentication/billing environment is inherited unchanged, not harvested or switched.
        kwargs: dict[str, Any] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        try:
            with private_file(out_path) as stdout, private_file(err_path) as stderr, tempfile.TemporaryFile() as stdin:
                stdin.write((spec.prompt + "\n").encode("utf-8"))
                stdin.seek(0)
                process = subprocess.Popen(command, cwd=spec.cwd, stdin=stdin, stdout=stdout,
                                           stderr=stderr, env=env, shell=False, close_fds=True, **kwargs)
                self.store.update(job["id"], pid=process.pid)
                started = time.monotonic()
                while process.poll() is None:
                    self.heartbeat()
                    if self.should_stop():
                        reason = "Worker stop requested during execution. Inspect partial work before rescheduling."
                    elif self.store.get(job["id"])["cancel_requested"]:
                        reason = "Job cancellation requested."
                    elif time.monotonic() - started >= spec.timeout_seconds:
                        reason = "Run timeout reached. Inspect partial work; no automatic retry."
                    elif out_path.stat().st_size + err_path.stat().st_size > spec.max_log_bytes:
                        reason = "Log size guard triggered. Inspect partial work; no automatic retry."
                    if reason:
                        safely_stopped = stop_child(process)
                        break
                    time.sleep(0.25)
        finally:
            if process is not None and process.poll() is None:
                safely_stopped = stop_child(process)
        assert process is not None
        code = process.poll()
        if reason or not safely_stopped:
            state = "cancelled" if safely_stopped and self.store.get(job["id"])["cancel_requested"] else "needs_review"
            self.store.finish(job["id"], state, reason or "The child may still be running; inspect it manually.",
                              exit_code=code, keep_pid=not safely_stopped)
        elif out_path.stat().st_size + err_path.stat().st_size > spec.max_log_bytes:
            self.store.finish(job["id"], "needs_review", "Log size guard exceeded; output not parsed.", exit_code=code)
        else:
            assert code is not None
            outcome = classify_file(spec.provider, spec.session_id, out_path, code)
            due = next_retry(job, outcome, time.time())
            if due is not None:
                self.store.finish(job["id"], "retry_wait", outcome.detail, exit_code=code, due_at=due)
            else:
                state = {"success": "completed", "review": "needs_review", "failure": "failed", "rate_limit": "failed"}[outcome.kind]
                detail = outcome.detail + (" Retry budget/window exhausted." if outcome.kind == "rate_limit" else "")
                self.store.finish(job["id"], state, detail, exit_code=code)
        finished = self.store.get(job["id"])
        self.log(f"{job['id'][:8]} {finished['status']}; logs: {stem}")


def start_background(store: Store) -> dict[str, Any]:
    if is_running(store.home):
        return {"already_running": True, **store.meta("worker", {})}
    env = os.environ.copy()
    # Supports both pip installs and `python -m ai_wakeup` from a source checkout.
    source_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUTF8"] = "1"
    args = [sys.executable, "-u", "-m", "ai_wakeup", "--home", str(store.home), "worker"]
    kwargs: dict[str, Any] = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt" else {"start_new_session": True}
    )
    with private_file(store.home / "worker.log", exclusive=False) as log:
        process = subprocess.Popen(args, cwd=store.home, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, close_fds=True, shell=False, **kwargs)
    for _ in range(50):
        state = store.meta("worker", {})
        if state.get("pid") == process.pid and state.get("state") == "running" and is_running(store.home):
            return {"already_running": False, **state}
        if process.poll() is not None:
            raise WakeupError(f"Worker exited during startup. Read {store.home / 'worker.log'}.")
        time.sleep(0.1)
    raise WakeupError(f"Worker readiness not confirmed. Check status and {store.home / 'worker.log'}; do not start duplicate schedulers.")


def request_stop(store: Store) -> str:
    if not is_running(store.home):
        return "No worker is currently running. Pending schedules remain saved."
    state = store.meta("worker", {})
    if not state.get("id"):
        raise WakeupError("Worker is still starting; retry stop in a moment.")
    store.set_meta("stop_requested", state["id"])
    return "Stop requested. An active child will be interrupted and may need review; pending jobs remain saved. Check status for confirmation."
