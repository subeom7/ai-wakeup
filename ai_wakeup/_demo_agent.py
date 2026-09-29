"""Simulation fixture: no provider/network/credential access. Not a real agent."""
from __future__ import annotations
import json
import os
import sys
import time


def emit(obj):
    print(json.dumps(obj), flush=True)


def main():
    provider, scenario, *args = sys.argv[1:]
    prompt = sys.stdin.buffer.read().decode("utf-8")
    marker = "resume" if provider == "codex" else "--resume"
    session = args[args.index(marker) + 1]
    if scenario == "wrong_session":
        session = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    if provider == "codex":
        emit({"type": "thread.started", "thread_id": session})
    else:
        emit({"type": "system", "subtype": "init", "session_id": session})
    if scenario == "sleep":
        time.sleep(30)
    if scenario == "flood":
        print("x" * 10000, flush=True)
        time.sleep(30)
    if scenario == "rate_limit":
        error = {"code": "usage_limit_exceeded", "message": "You've hit your usage limit", "retry_after_seconds": 900}
        emit({"type": "turn.failed", "error": error} if provider == "codex" else
             {"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": session, "error": error})
        return 1
    if scenario == "unknown_failure":
        print("Unknown transport problem", file=sys.stderr)
        return 9
    if scenario == "silent_success":
        return 0
    if provider == "codex":
        emit({"type": "item.completed", "item": {"type": "agent_message", "text": "simulated only", "cwd": os.getcwd(), "stdin": prompt}})
        emit({"type": "turn.completed", "usage": {"input_tokens": 0, "output_tokens": 0}})
    else:
        emit({"type": "result", "subtype": "success", "is_error": False, "session_id": session,
              "permission_denials": ([{"tool_name": "Bash"}] if scenario == "denied" else []), "result": "simulated only"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
