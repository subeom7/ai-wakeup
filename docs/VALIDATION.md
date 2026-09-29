# Validation record — 0.1.0a1

Recorded on 2026-09-29 while preparing the initial source snapshot.

## Actually executed

Environment: **Linux, Python 3.13.5**.

| Check | Observed result |
|---|---|
| `python -m unittest discover -s tests -v` | **82 tests passed**, 19.317 seconds |
| Simulated Codex child | Spawned a real local Python child, checked UUID/cwd/stdin, recorded successful turn |
| Simulated Claude child | Spawned a real local Python child, checked success/denial/rate-failure behavior |
| Local detached worker | Launcher exited; worker stayed running; duplicate start reused it; second worker lock rejected; cooperative stop completed |
| Timeout and cancellation | Running simulation was stopped and ledger updated |
| Crash recovery | Interrupted jobs held for review, not automatically replayed |
| Unicode and shell metacharacters | Prompt transported on stdin; project path with Korean text, spaces, and ampersand exercised |
| Package wheel | Built successfully as `ai_wakeup-0.1.0a1-py3-none-any.whl` |
| Independent installation | Installed that wheel without dependencies into a fresh virtual environment |
| Installed entry point | `ai-wakeup --version` returned `0.1.0a1` outside the source checkout |
| Installed simulated demo | Completed successfully outside the source checkout without AI provider calls |

The full unit/simulation test transcript is in [test-results.txt](test-results.txt). A wheel's `py3-none-any` tag is packaging metadata, not evidence that every platform was tested.

## NOT executed or established

- Windows execution, Windows terminal-closure behavior, or Windows process-tree cleanup.
- macOS execution.
- Authenticated `codex exec resume` or `claude --resume --print` on a real account.
- A genuine subscription usage-limit reset followed by successful resume.
- Effective sandbox/permission guarantees for a particular installed provider version.
- Exact restoration of TUI model/effort/settings, unsaved input, or background tools.
- GitHub Actions runs in the remote repository; the workflow has only been authored.
- A GitHub push, release, PyPI upload, or package-name ownership check.

The generated tests verify this implementation against documented/simulated event shapes, not a claim that every upstream version uses identical shapes. The CLI documentation and Codex argument structure were inspected through official upstream sources on 2026-09-29. The adapters must still be acceptance-tested against the user's actual installed versions.

## Next acceptance test

Use a disposable git worktree and a noncritical saved session. Record OS, Python version, `codex --version` / `claude --version`, the preview, exit state, and sanitized logs. Start with a read/plan-only request. Verify a small permitted edit separately. Only after those pass, test a real rate-limit-reset cycle. Keep competing supervisors disabled for that session. Do not publish raw credentials, session transcripts, or sensitive paths.
