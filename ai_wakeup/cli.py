"""Small, explicit CLI. No shell-profile edits, hooks, or hidden auto-enrollment."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from . import __version__
from .core import (DEFAULT_PROMPT, JobSpec, WakeupError, absolute_time, build_command,
                   data_home, duration, resolve_executable, safe_text, session_uuid, time_label)
from .store import Store
from .worker import Worker, is_running, request_stop, start_background


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="ai-wakeup", description="Schedule one existing Claude Code or Codex session. Local-only alpha; no quota bypass.")
    result.add_argument("--version", action="version", version=f"ai-wakeup {__version__}")
    result.add_argument("--home", help="State directory (default: AI_WAKEUP_HOME or ~/.ai-wakeup). Put this option before the command.")
    sub = result.add_subparsers(dest="command", required=True)
    schedule = sub.add_parser("schedule", help="Explicitly register one existing session; does not start a worker.")
    schedule.add_argument("provider", choices=("codex", "claude"))
    schedule.add_argument("--session", required=True, help="Full session UUID, never --last.")
    schedule.add_argument("--cwd", required=True, help="Trusted project directory.")
    when = schedule.add_mutually_exclusive_group(required=True)
    when.add_argument("--at", help="ISO timestamp with date and offset, e.g. 2026-09-30T01:15:00+09:00.")
    when.add_argument("--after", help="Relative delay, e.g. 15m or 4h.")
    prompts = schedule.add_mutually_exclusive_group()
    prompts.add_argument("--prompt", default=None, help="Follow-up prompt. Stored locally; may appear in your shell history.")
    prompts.add_argument("--prompt-file", help="UTF-8 text file; useful for sensitive or multiline instructions.")
    schedule.add_argument("--allow-edits", action="store_true", help="Opt in to Codex workspace-write / Claude acceptEdits. Does not disable sandboxing or approve all tools.")
    schedule.add_argument("--model", help="Explicit model override; omitted means CLI/session configuration, not guaranteed TUI parity.")
    schedule.add_argument("--executable", help="Official CLI executable path. Shell aliases/wrappers are not invoked.")
    schedule.add_argument("--max-attempts", type=int, default=3, help="1-10, including first attempt; retries only for recognized provider rate-limit errors.")
    schedule.add_argument("--retry-every", default="15m", help="Base retry delay (at least 60s); exponential backoff.")
    schedule.add_argument("--timeout", default="1h", help="Maximum duration per process, at most 1d.")
    schedule.add_argument("--expires-after", default="24h", help="Stop trying this long after the scheduled time.")
    schedule.add_argument("--json", action="store_true")
    status = sub.add_parser("status", help="Worker health and saved job states; no provider API calls.")
    status.add_argument("--json", action="store_true")
    preview = sub.add_parser("preview", help="Show the exact planned arguments and timing without executing.")
    preview.add_argument("job", nargs="?")
    preview.add_argument("--show-prompt", action="store_true")
    preview.add_argument("--json", action="store_true")
    cancel = sub.add_parser("cancel", help="Cancel a queued job or request termination of a running child.")
    cancel.add_argument("job")
    resolve = sub.add_parser("resolve", help="Close a needs_review job only after verifying its previous process stopped.")
    resolve.add_argument("job")
    resolve.add_argument("--acknowledge-stopped", action="store_true", required=True)
    logs = sub.add_parser("logs", help="Read the latest attempt's local log; terminal controls are stripped.")
    logs.add_argument("job")
    logs.add_argument("--stream", choices=("stdout", "stderr"), default="stdout")
    logs.add_argument("--lines", type=int, default=50)
    doctor = sub.add_parser("doctor", help="Resolve executable paths and run --version. Does not validate authentication/quota.")
    doctor.add_argument("--provider", choices=("codex", "claude"))
    doctor.add_argument("--executable", help="Native executable override; requires --provider.")
    sub.add_parser("start", help="Explicitly start a detached worker; no login/startup service is installed.")
    sub.add_parser("stop", help="Request worker stop; pending jobs remain saved.")
    worker = sub.add_parser("worker", help="Run the worker in this terminal (keep it open).")
    worker.add_argument("--once", action="store_true", help="Claim at most one currently-due job, then exit.")
    worker.add_argument("--poll", type=float, default=1, help="Local database polling interval, 0.1-60 seconds; not provider/API polling.")
    sub.add_parser("demo", help="Run an isolated simulated resume; no installed agents, API calls, or credentials needed.")
    return result


def summary(store: Store, job: dict[str, Any]) -> dict[str, Any]:
    spec = store.spec(job)
    return {"id": job["id"], "provider": spec.provider, "session_id": spec.session_id,
            "cwd": spec.cwd, "status": job["status"], "due_at": time_label(job["due_at"]),
            "expires_at": time_label(job["expires_at"]), "attempts": job["attempts"],
            "max_attempts": job["max_attempts"], "allow_edits": spec.allow_edits,
            "pid": job["pid"], "cancel_requested": bool(job["cancel_requested"]),
            "exit_code": job["exit_code"], "detail": safe_text(job["last_error"] or ""),
            "log_base": job["log_base"]}


def schedule_job(args: argparse.Namespace, store: Store) -> int:
    now = time.time()
    due = absolute_time(args.at) if args.at else now + duration(args.after)
    if due <= now:
        raise WakeupError("Scheduled time must be in the future. Use --after 10s for a quick test.")
    cwd = Path(args.cwd).expanduser().resolve(strict=True)
    if not cwd.is_dir():
        raise WakeupError("Project path is not a directory.")
    prompt = DEFAULT_PROMPT if args.prompt is None else args.prompt
    if args.prompt_file:
        path = Path(args.prompt_file).expanduser()
        if path.stat().st_size > 32768:
            raise WakeupError("Prompt file is larger than 32 KiB.")
        prompt = path.read_text(encoding="utf-8-sig")
    spec = JobSpec(provider=args.provider, session_id=session_uuid(args.session), cwd=str(cwd),
                   prompt=prompt, executable=resolve_executable(args.provider, args.executable),
                   allow_edits=args.allow_edits, model=args.model,
                   retry_seconds=duration(args.retry_every), timeout_seconds=duration(args.timeout))
    job = store.add(spec, due, due + duration(args.expires_after), args.max_attempts)
    if args.json:
        print(json.dumps(summary(store, job), ensure_ascii=False, indent=2))
    else:
        print(f"Scheduled {job['id']}\n  {spec.provider} session: {spec.session_id}\n  Project: {cwd}\n  Wake at: {time_label(due)}")
        print("  Permissions: " + ("Explicit edit opt-in; other approvals still apply." if spec.allow_edits else "Codex read-only / Claude plan mode (not equivalent security boundaries)."))
        print("This registers a schedule, not proof of a valid session, login, quota, or future success.")
        print("Stop other agents/schedulers on this same session before starting the worker.")
        if not is_running(store.home):
            print("Worker is STOPPED. Review with preview, then run: ai-wakeup start")
    return 0


def show_status(args: argparse.Namespace, store: Store) -> int:
    active = is_running(store.home)
    meta = store.meta("worker", {})
    jobs = [summary(store, job) for job in store.list_jobs()]
    state = {"home": str(store.home), "worker_lock_held": active, "worker": meta, "jobs": jobs}
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    print(f"ai-wakeup {__version__} | state: {store.home}")
    if active:
        age = time.time() - meta.get("heartbeat_at", 0)
        print(f"Worker: {'RUNNING' if age < 15 else 'LOCKED / heartbeat stale'} | PID {meta.get('pid', '?')} | heartbeat {age:.1f}s ago")
    else:
        print("Worker: STOPPED (queued jobs will NOT execute until a worker is started)")
    if not jobs:
        print("0 jobs. Nothing will be resumed.")
    for job in jobs:
        print(f"\n{job['id']}  {job['status'].upper()}  {job['provider']}")
        print(f"  Session {job['session_id']} | {job['cwd']}")
        print(f"  Due {job['due_at']} | attempts {job['attempts']}/{job['max_attempts']}")
        if job["detail"]:
            print(f"  {job['detail']}")
    return 0


def show_preview(args: argparse.Namespace, store: Store) -> int:
    jobs = [store.get(args.job)] if args.job else store.list_jobs()
    previews = []
    for job in jobs:
        spec = store.spec(job)
        item = summary(store, job)
        item.update({"argv": build_command(spec), "shell": False, "prompt_transport": "stdin",
                     "worker_running": is_running(store.home), "seconds_until_due": round(job["due_at"] - time.time()),
                     "session_and_auth_verified": False})
        if args.show_prompt:
            item["prompt"] = spec.prompt
        previews.append(item)
    if args.json:
        print(json.dumps(previews, ensure_ascii=False, indent=2))
    else:
        print("PREVIEW ONLY: no agent launched, no input sent, no job state changed.")
        if not previews:
            print("No registered jobs.")
        for item in previews:
            print(safe_text(json.dumps(item, ensure_ascii=False, indent=2)))
        print("CLI hooks/configuration remain in effect. Close the original interactive session and disable any competing scheduler for this session.")
    return 0


def show_logs(args: argparse.Namespace, store: Store) -> int:
    if not 1 <= args.lines <= 10000:
        raise WakeupError("--lines must be between 1 and 10000.")
    job = store.get(args.job)
    if not job["log_base"]:
        print("No attempt has started; no provider log exists yet.")
        return 0
    suffix = ".stdout.jsonl" if args.stream == "stdout" else ".stderr.log"
    path = store.home / "logs" / (job["log_base"] + suffix)
    if path.parent.resolve() != (store.home / "logs").resolve():
        raise WakeupError("Invalid log path in the state database.")
    print(f"Local log (may contain private source/data): {path}")
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in deque(stream, maxlen=args.lines):
            print(safe_text(line), end="")
    return 0


def doctor(args: argparse.Namespace, store: Store) -> int:
    if args.executable and not args.provider:
        raise WakeupError("--executable requires --provider.")
    print(f"Python: {sys.version.split()[0]} | OS: {sys.platform}\nState: {store.home}")
    print(f"Worker: {'running' if is_running(store.home) else 'stopped'}")
    available = 0
    for provider in ([args.provider] if args.provider else ["codex", "claude"]):
        try:
            executable = resolve_executable(provider, args.executable)
            print(f"{provider} argv prefix: {json.dumps(executable)}")
            completed = subprocess.run([*executable, "--version"], stdin=subprocess.DEVNULL,
                                       capture_output=True, timeout=10, check=False, shell=False)
            text = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").strip()
            print(f"  version exit={completed.returncode}: {safe_text(text)[:500]}")
            available += int(completed.returncode == 0)
        except (WakeupError, OSError, subprocess.TimeoutExpired) as exc:
            print(f"{provider}: {safe_text(exc)}")
    keys = [key for key in ("CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL") if os.environ.get(key)]
    if keys:
        print("Provider environment variables PRESENT (values hidden): " + ", ".join(keys))
        print("These may affect provider/billing selection. ai-wakeup does not change them or switch accounts.")
    print("Authentication/quota/session existence/permission effectiveness: NOT verified.")
    print("No sign-in service or sleep-prevention setting is installed. Keep the computer awake and connected.")
    return 0 if available else 1


def demo() -> int:
    print("SIMULATION ONLY: no Claude/Codex invocation, network request, or credential access.")
    with tempfile.TemporaryDirectory(prefix="ai-wakeup-demo-") as root:
        store = Store(Path(root) / "state")
        spec = JobSpec("codex", str(uuid.uuid4()), root, "Demonstrate a successful turn.",
                       (sys.executable, str(Path(__file__).with_name("_demo_agent.py")), "codex", "success"))
        job = store.add(spec, time.time() - 1, time.time() + 60, 1)
        Worker(store).run(once=True)
        status = store.get(job["id"])["status"]
        print(f"Simulated job: {status}. Temporary data will be deleted.")
        return 0 if status == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            return demo()
        store = Store(data_home(args.home))
        if args.command == "schedule":
            return schedule_job(args, store)
        if args.command == "status":
            return show_status(args, store)
        if args.command == "preview":
            return show_preview(args, store)
        if args.command == "logs":
            return show_logs(args, store)
        if args.command == "doctor":
            return doctor(args, store)
        if args.command == "cancel":
            print(store.cancel(args.job))
        elif args.command == "resolve":
            store.resolve(args.job)
            print("Review acknowledged; job closed without restarting it.")
        elif args.command == "start":
            state = start_background(store)
            print(f"Worker {'already running' if state['already_running'] else 'started'} (PID {state.get('pid')}).")
            print("No login/startup service installed. Keep this computer awake; confirm status before leaving.")
        elif args.command == "stop":
            print(request_stop(store))
        elif args.command == "worker":
            return Worker(store, poll_seconds=args.poll).run(once=args.once)
        return 0
    except (WakeupError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"ai-wakeup: {safe_text(exc)}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
