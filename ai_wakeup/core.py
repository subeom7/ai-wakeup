"""Pure validation, time handling, and provider command construction."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import uuid
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PROMPT = (
    "Continue the unfinished task in this session. Stay within its existing scope "
    "and the current permissions. Do not deploy, publish, push commits, change "
    "billing, or weaken security settings. Stop when finished or when approval "
    "is required."
)
ACTIVE_STATES = ("queued", "retry_wait", "running", "needs_review")
TERMINAL_STATES = ("completed", "failed", "cancelled", "expired")


class WakeupError(Exception):
    """An actionable user error; the CLI prints it without a traceback."""


def duration(value: str) -> float:
    """Parse one explicitly unit-qualified duration, e.g. 90s, 15m, 2h."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(s|m|h|d)", value.strip())
    if not match:
        raise WakeupError("Use a duration such as 30s, 15m, 2h, or 1d.")
    number = float(match[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match[2]]
    if not math.isfinite(number) or not 0 < number <= 365 * 86400:
        raise WakeupError("Duration must be positive and at most 365 days.")
    return number


def absolute_time(value: str) -> float:
    """Require a date AND UTC offset: no ambiguous local-time guesses."""
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise WakeupError("Use ISO time, e.g. 2026-09-30T01:15:00+09:00.") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise WakeupError("An explicit UTC offset is required, e.g. +09:00 or Z.")
    return dt.timestamp()


def time_label(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).astimezone().isoformat(timespec="seconds")


def session_uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise WakeupError("Use the full session UUID, not --last, a name, or a short prefix.") from exc
    return str(parsed)


def safe_text(value: object) -> str:
    """Avoid replaying terminal control sequences from provider output."""
    text = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))", "", str(value))
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))


def data_home(override: str | None = None) -> Path:
    value = override or os.environ.get("AI_WAKEUP_HOME")
    path = Path(value).expanduser() if value else Path.home() / ".ai-wakeup"
    return path.resolve()


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise WakeupError(f"Not a directory: {path}")
    # On Windows the user's profile ACL applies. No ACL changes are attempted.
    if os.name != "nt":
        path.chmod(0o700)


def resolve_executable(provider: str, override: str | None = None) -> tuple[str, ...]:
    """Resolve real executables, never shell aliases/functions or arbitrary .cmd files."""
    if provider not in ("codex", "claude"):
        raise WakeupError("Provider must be codex or claude.")
    if override:
        candidate = Path(override).expanduser()
        found = str(candidate) if candidate.is_file() else shutil.which(override)
    else:
        found = (shutil.which(provider + ".exe") if os.name == "nt" else None) or shutil.which(provider)
    if not found:
        raise WakeupError(f"{provider} executable not found. Install/login to the official CLI first, or use --executable.")
    path = Path(found).resolve()
    suffix = path.suffix.lower()
    if suffix in (".cmd", ".bat", ".ps1"):
        # Invoke the known npm Codex entry point using node, without cmd.exe.
        entry = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node")
        if provider == "codex" and suffix == ".cmd" and entry.is_file() and node:
            return str(Path(node).resolve()), str(entry.resolve())
        raise WakeupError("Shell wrappers are not executed. Pass --executable with the native .exe path (Codex npm shims with a known Node entry point are supported).")
    if not path.is_file():
        raise WakeupError(f"Executable is not a file: {path}")
    if os.name != "nt" and not os.access(path, os.X_OK):
        raise WakeupError(f"File is not executable: {path}")
    return (str(path),)


@dataclass(frozen=True)
class JobSpec:
    provider: str
    session_id: str
    cwd: str
    prompt: str
    executable: tuple[str, ...]
    allow_edits: bool = False
    model: str | None = None
    retry_seconds: float = 900
    timeout_seconds: float = 3600
    max_log_bytes: int = 20 * 1024 * 1024

    def validate(self) -> None:
        if self.provider not in ("codex", "claude"):
            raise WakeupError("Unsupported provider.")
        if self.session_id != session_uuid(self.session_id):
            raise WakeupError("Session ID must be a canonical UUID.")
        if not Path(self.cwd).is_absolute():
            raise WakeupError("The project path must be absolute.")
        if not self.executable or not Path(self.executable[0]).is_absolute():
            raise WakeupError("The executable path must be absolute.")
        if not self.prompt.strip() or len(self.prompt.encode("utf-8")) > 32768 or "\0" in self.prompt:
            raise WakeupError("Prompt must contain text, no NUL, and at most 32 KiB UTF-8.")
        if self.model is not None and (not self.model or self.model.startswith("-") or "\0" in self.model or len(self.model) > 200):
            raise WakeupError("Invalid model name.")
        if not math.isfinite(self.retry_seconds) or not 60 <= self.retry_seconds <= 86400:
            raise WakeupError("Retry interval must be between 60 seconds and 1 day.")
        if not math.isfinite(self.timeout_seconds) or not 1 <= self.timeout_seconds <= 86400:
            raise WakeupError("Run timeout must be between 1 second and 1 day.")
        if not 1024 <= self.max_log_bytes <= 100 * 1024 * 1024:
            raise WakeupError("Log limit must be between 1 KiB and 100 MiB.")


def build_command(spec: JobSpec) -> list[str]:
    """The prompt is supplied on stdin, not interpolated into a shell command."""
    spec.validate()
    args = list(spec.executable)
    if spec.provider == "codex":
        args += ["exec", "--json", "--color", "never", "-c", 'approval_policy="never"',
                 "-c", 'sandbox_mode="workspace-write"' if spec.allow_edits else 'sandbox_mode="read-only"']
        if spec.model:
            args += ["--model", spec.model]
        args += ["resume", spec.session_id, "-"]
    else:
        args += ["--resume", spec.session_id, "--print", "--output-format", "stream-json", "--verbose",
                 "--permission-mode", "acceptEdits" if spec.allow_edits else "plan"]
        if spec.model:
            args += ["--model", spec.model]
    return args


def serialize_spec(spec: JobSpec) -> str:
    from dataclasses import asdict
    return json.dumps(asdict(spec), ensure_ascii=False)


def deserialize_spec(text: str) -> JobSpec:
    obj = json.loads(text)
    obj["executable"] = tuple(obj["executable"])
    spec = JobSpec(**obj)
    spec.validate()
    return spec
