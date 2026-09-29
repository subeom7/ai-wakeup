"""Conservative provider-event classification, not transcript keyword matching.

Only top-level provider failure envelopes can request retry. Assistant text,
tool output, ordinary stderr, and unknown schemas never authorize a retry.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RATE_CODES = {"usage_limit_exceeded", "rate_limit_exceeded", "rate_limit_error", "rate_limit"}
RATE_PREFIXES = ("you've hit your usage limit", "you’ve hit your usage limit",
                 "you have hit your usage limit", "rate limit exceeded", "rate limit reached")


@dataclass(frozen=True)
class Outcome:
    kind: str  # success, rate_limit, failure, review
    detail: str
    retry_after: float | None = None


def error_info(error: Any) -> tuple[bool, str, float | None]:
    retry_after = None
    code = ""
    if isinstance(error, dict):
        nested = error.get("error")
        if isinstance(nested, dict):
            return error_info(nested)
        code = str(error.get("code", error.get("type", ""))).lower()
        message = str(error.get("message", error.get("error", "")))
        hint = error.get("retry_after_seconds", error.get("retry_after"))
        if isinstance(hint, (float, int)) and not isinstance(hint, bool) and math.isfinite(hint) and hint >= 0:
            retry_after = float(hint)
    elif isinstance(error, str):
        message = error
    else:
        message = "Unrecognized provider error payload."
    # A known non-rate code (e.g. authentication_error) takes precedence over text.
    rate = code in RATE_CODES or (not code and message.strip().lower().startswith(RATE_PREFIXES))
    return rate, message[:2000] or code or "Provider returned an error.", retry_after


class EventClassifier:
    def __init__(self, provider: str, session_id: str):
        self.provider = provider
        self.session_id = session_id
        self.terminal: str | None = None
        self.last_error: Any = None
        self.permission_denied = False
        self.session_mismatch = False

    def feed(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if self.provider == "codex":
            if kind == "thread.started":
                identity = event.get("thread_id")
                if identity is not None and identity != self.session_id:
                    self.session_mismatch = True
            elif kind == "turn.completed":
                self.terminal = "success"
                self.last_error = None
            elif kind == "turn.failed":
                self.terminal = "failure"
                self.last_error = event.get("error")
            elif kind == "error":
                # A transient error followed by turn.completed is not a failed job.
                self.last_error = event.get("error", {key: value for key, value in event.items() if key != "type"})
                self.terminal = "failure"
        elif self.provider == "claude":
            if kind == "system" and event.get("subtype") == "init":
                identity = event.get("session_id")
                if identity is not None and identity != self.session_id:
                    self.session_mismatch = True
            elif kind == "result":
                identity = event.get("session_id")
                if identity is not None and identity != self.session_id:
                    self.session_mismatch = True
                self.permission_denied = bool(event.get("permission_denials"))
                if event.get("is_error") is False and event.get("subtype") == "success":
                    self.terminal = "success"
                    self.last_error = None
                else:
                    self.terminal = "failure"
                    # Rate retry is accepted only when Claude itself marks this a failure.
                    errors = event.get("errors")
                    self.last_error = event.get("error") or (errors[-1] if isinstance(errors, list) and errors else None) or event.get("result")
            elif kind == "error":
                self.terminal = "failure"
                self.last_error = event.get("error", {key: value for key, value in event.items() if key != "type"})

    def outcome(self, exit_code: int) -> Outcome:
        if self.session_mismatch:
            return Outcome("review", "Provider reported a different session ID. Inspect the logs; automatic retry is disabled.")
        if self.permission_denied:
            return Outcome("review", "The provider reported denied permissions; no automatic approval was attempted.")
        if self.terminal == "success" and exit_code == 0:
            return Outcome("success", "Provider reported that this turn completed. This does not prove the whole project is finished.")
        if self.terminal == "failure":
            rate, detail, retry = error_info(self.last_error)
            return Outcome("rate_limit" if rate else "failure", detail, retry)
        if exit_code != 0:
            return Outcome("failure", f"CLI exited with code {exit_code}; no recognized provider rate-limit event. Inspect stderr.")
        return Outcome("review", "CLI exited without a recognized completion event. Inspect logs/version compatibility; no automatic replay.")


def classify_file(provider: str, session_id: str, path: Path, exit_code: int) -> Outcome:
    classifier = EventClassifier(provider, session_id)
    # The runner bounds total log size. Avoid unbounded individual JSON lines too.
    with path.open("rb") as stream:
        while True:
            raw = stream.readline(1024 * 1024 + 1)
            if not raw:
                break
            if len(raw) > 1024 * 1024:
                return Outcome("review", "A provider event exceeded 1 MiB; inspect the raw log.")
            try:
                classifier.feed(json.loads(raw))
            except (ValueError, UnicodeError):
                continue
    return classifier.outcome(exit_code)
