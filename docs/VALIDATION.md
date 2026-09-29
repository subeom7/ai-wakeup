# Validation record — 0.1.0a1

Recorded on 2026-09-29 while preparing the initial source snapshot.

The sections below through **Next acceptance test** are the historical source-generation record. For repository/CI follow-up, see the final section and the linked Actions runs.

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

## Repository setup follow-up — 2026-09-29

The initial import commit `c9175d7518cf541c8ef9016b311bf3930e2f83e1` preserved all 31 files from the provided ZIP byte-for-byte (Git tree `1b172f0f96ac02fa6b9ca77314e98f14797d2520`). Local Linux/Python 3.13.5 reruns also passed all 82 tests.

The [first PR CI run](https://github.com/subeom7/ai-wakeup/actions/runs/36575862441) passed both Ubuntu jobs and exposed two test-fixture portability issues on the other runners:

- Windows: the schema-version test left its own SQLite connection open, blocking temporary-directory cleanup. The fixture now closes it explicitly; production ledger connections already used explicit closing.
- macOS: the successful child-process test compared path spelling rather than directory identity (`/var` versus `/private/var`). It now verifies `samefile`, keeping the working-directory assertion in place.

These fixes do not change runtime behavior, remove tests, or add skips. The complete suite still contains 82 tests. See [PR #1](https://github.com/subeom7/ai-wakeup/pull/1) and the [Actions history](https://github.com/subeom7/ai-wakeup/actions/workflows/ci.yml) for the result attached to each subsequent commit; the failed initial run is retained as evidence.

Hosted CI exercises local simulated child processes and package installation. It does not validate authenticated Claude/Codex execution, a real subscription reset, the user's Windows Terminal configuration, or effective provider permissions. No GitHub release or PyPI package is published by this setup.
