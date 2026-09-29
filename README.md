# ai-wakeup

**Paused sessions deserve a wake-up call.**

An explicit, local scheduler for resuming an existing **Codex CLI** or **Claude Code** session after a wait. Select the exact session, review the planned invocation, and let a small worker launch it at the time you choose.

[한국어 안내](README.ko.md) · [Architecture](docs/ARCHITECTURE.md) · [Validation](docs/VALIDATION.md) · [Roadmap](docs/ROADMAP.md)

> **0.1.0a1 — experimental alpha.** This is a working scheduled-resume implementation, **not yet a drop-in replacement for unsnooze**. The first schedule requires a user-supplied session UUID and time. It does not automatically discover already-open sessions or infer their reset timestamps. Automated tests use simulated agents; consult the repository CI for hosted-platform results. Authenticated provider runs and end-user terminal-lifecycle behavior still need validation. No guarantee of uninterrupted or complete work is made.

## What is implemented

| Capability | This release |
|---|---|
| Schedule an exact Codex / Claude session | `schedule`, by full UUID and project directory |
| Absolute or relative time | Offset-qualified ISO timestamp, or `--after 4h` |
| Persistent local state | SQLite queue; all scheduled times stored as UTC timestamps |
| Preview | Exact argument array, permission choice, time, and worker state; no agent invocation |
| Foreground / detached worker | `worker`, or explicit `start` / `stop` |
| Retry after another rate limit | Recognized provider failure envelopes only; bounded exponential backoff |
| Duplicate prevention | One worker per state directory, one active job per provider/session; unresolved workspace jobs block new claims in that workspace |
| Crash safety | Interrupted jobs become `needs_review`, never automatically replayed |
| Diagnostics | `doctor`, `status`, per-attempt stdout/stderr logs |
| Local simulated demo | Real child-process execution with a fake agent; no provider calls |

Python **3.11+**, with **no third-party runtime dependencies**. Packaging uses setuptools. The project was written independently; it is not a fork of unsnooze.

## Install and try without an AI account

From the repository / extracted source directory:

```powershell
py -m pip install .
py -m ai_wakeup demo
py -m ai_wakeup --help
```

On Linux/macOS use `python3` instead of `py`. An `ai-wakeup` command is also installed, but `py -m ai_wakeup` avoids Windows Scripts/PATH confusion. The module can also run directly from the source root without installing it.

**Do not use `pip install ai-wakeup` from an unverified registry listing.** This source snapshot has not been published to PyPI; name availability has not been established.

## Schedule a real session

First, use and log in to the official CLI normally. Obtain the full UUID of the saved session you want to resume. This release does not select a session for you. Stop its interactive execution and cancel any competing unsnooze/other scheduler reservation **for that same session**. Do not run two supervisors against the same worktree.

Inspect the local executable setup:

```powershell
py -m ai_wakeup doctor
```

`doctor` checks executable resolution and `--version`; it does **not** prove login validity, account quota, session existence, effective permissions, or successful resume.

Replace the UUID and path below with your own. This example uses a **relative delay of four hours**, not an automatically detected reset:

```powershell
py -m ai_wakeup schedule codex `
  --session "0199a213-81c0-7800-8aa1-bbab2a035a53" `
  --cwd "C:\work\your-project" `
  --after 4h `
  --allow-edits
```

For Claude Code, use `schedule claude` instead. To choose a precise future date/time, replace `--after 4h` with an offset-qualified value such as `--at "2026-09-30T01:15:00+09:00"` **after updating the example to your actual future reset date**. A naive value such as `01:15` is rejected. Use a small buffer after the provider's displayed reset time if needed.

Review the registered job before starting anything:

```powershell
py -m ai_wakeup preview
py -m ai_wakeup start
py -m ai_wakeup status
```

Registration alone does not start the worker. `start` explicitly launches a detached process. No Windows Scheduled Task, login service, shell wrapper, or provider hook is installed. Keep the computer awake, connected, and signed in. After closing the launch terminal, check `status` in another terminal: a terminal/OS job manager may still end its children. Windows detachment remains pending real-machine validation. Alternatively keep `py -m ai_wakeup worker` open in its own terminal.

## Permissions and continuation instructions

Defaults are deliberately conservative:

| Provider | Default | With explicit `--allow-edits` |
|---|---|---|
| Codex | `sandbox_mode="read-only"` | `sandbox_mode="workspace-write"` |
| Claude | `--permission-mode plan` | `--permission-mode acceptEdits` |

Codex is passed `approval_policy="never"`: requests that need additional approval are not automatically approved. Claude's edit acceptance is not a blanket tool approval. Other operations may be denied or wait until the configured timeout. **Claude plan mode and Codex read-only sandboxing are not identical security boundaries.** Project/user configuration, provider hooks, enabled integrations, and actual CLI behavior still matter; inspect them before unattended use.

The tool never adds `--dangerously-skip-permissions`, `--yolo`, or a full-access sandbox flag. `--allow-edits` does not promise that every test, shell command, or network operation can run. Use a test repository first, inspect the actual result, and do not run against production credentials or a sensitive worktree until verified.

A default follow-up asks the agent to continue only unfinished work, stay within the current scope/permissions, and not deploy, publish, push commits, alter billing, or weaken security. It is an instruction, not a security boundary. Override it with `--prompt` or a UTF-8 `--prompt-file`. Prompts supplied on the command line may remain in shell history; the provider receives the follow-up via stdin. Local queue storage contains the prompt in plaintext.

Optional `--model` is explicit; omitted model/effort settings depend on the provider's saved session/configuration. Exact TUI setting parity is **not** guaranteed. Only content saved by the provider can be resumed; unsaved/failed-to-persist messages cannot be reconstructed by this tool.

## State and recovery

```text
queued -> running -> completed
                   -> retry_wait -> running
                   -> failed
                   -> needs_review
queued/retry_wait -> cancelled or expired
```

`completed` means the provider emitted a successful **turn completion** and exited successfully, not that the whole project is done. Unknown successful-looking output is `needs_review`, not success. Authentication errors, billing/insufficient-quota errors, generic network failures, and permission issues do not cause blind automatic retries.

Defaults: at most **3 attempts total**, **15-minute** base backoff, **1-hour** per-attempt timeout, and expiration **24 hours after the scheduled time**. Known numeric retry hints can extend the delay, never shorten it below backoff. Change these with `--max-attempts`, `--retry-every`, `--timeout`, and `--expires-after`. Logs have a size guard; an oversize output run is stopped for review. This is a polling guard, not a hard filesystem quota.

```powershell
py -m ai_wakeup status
py -m ai_wakeup logs <JOB_ID>
py -m ai_wakeup logs <JOB_ID> --stream stderr
py -m ai_wakeup cancel <JOB_ID>
py -m ai_wakeup stop
```

Stopping the worker interrupts an active child and can leave partial work requiring review. Queued jobs remain saved. Queued jobs that become overdue may run after a later explicit `start`, unless expired or cancelled.

After a worker crash, inspect logs, the working tree, and any remaining agent/child processes. The tool will not kill an arbitrary PID recorded in a previous worker's database. Only after independently verifying that execution has stopped:

```powershell
py -m ai_wakeup resolve <JOB_ID> --acknowledge-stopped
```

This closes the job **without** replaying it. Schedule a new job explicitly if appropriate. Process-tree termination is best effort. Separate data directories, unrelated interactive terminals, and other schedulers are outside this release's duplicate prevention.

## Windows executable resolution

The worker invokes a resolved executable directly with `shell=False`, not a PowerShell function or alias. Prefer the official native `codex.exe` / `claude.exe`. When necessary pass `--executable "C:\path\to\codex.exe"` while scheduling, and use `doctor --provider codex --executable ...` to inspect it.

A known npm Codex shim layout is handled by directly invoking Node and its `node_modules/@openai/codex/bin/codex.js` entry point. Arbitrary `.cmd`, `.bat`, and `.ps1` wrappers are rejected rather than routed through `cmd.exe` with model/user text. WSL and native Windows installs are separate environments; use the same environment where the actual provider session exists.

## Privacy and boundaries

All scheduler state is local, by default under `~/.ai-wakeup`. Override with `AI_WAKEUP_HOME` or `--home PATH` **before** the subcommand. No telemetry, cloud service, remote listener, account switching, credential extraction, or quota-bypass mechanism is implemented. The launched provider CLI can of course contact its own services.

The provider inherits your existing authentication environment unchanged. Existing API-key/environment configuration can affect billing; **this tool cannot guarantee that a provider invocation uses a subscription instead of API credits**. `doctor` reports the presence of relevant variable names without printing their values. It never purchases credits or sets a fallback account.

The queue and logs can contain private prompts, source code, filesystem paths, and provider output. They are not encrypted and are not automatically redacted. Do not upload them to public issues without review. POSIX state-directory permissions are tightened to 0700 and DB/log files to 0600; on Windows your profile ACL applies. See [SECURITY.md](SECURITY.md).

## Development

```powershell
py -m unittest discover -s tests -v
py -m ai_wakeup demo
```

The included GitHub Actions workflow runs Linux, Windows, and macOS jobs on Python 3.11 and 3.13. See [Actions](https://github.com/subeom7/ai-wakeup/actions/workflows/ci.yml) for actual per-commit results and [the validation record](docs/VALIDATION.md) for the original local checks and repository setup follow-up. **Passing simulated CI is not authenticated provider validation.**

## Upstream interfaces

The adapters target the official documented non-interactive resume interfaces; behavior is CLI-version-sensitive:

- [OpenAI: non-interactive mode](https://developers.openai.com/codex/noninteractive/)
- [OpenAI: CLI reference](https://developers.openai.com/codex/cli/reference/)
- [Claude Code: CLI reference](https://code.claude.com/docs/en/cli-reference)

This project is not affiliated with or endorsed by OpenAI or Anthropic.

## License

[MIT](LICENSE). Copyright 2026 ai-wakeup contributors.
