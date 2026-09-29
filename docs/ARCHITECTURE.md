# Architecture: scheduled-resume alpha

## Components

`core.py` validates full UUIDs, timezone-qualified timestamps, durations, typed job settings, trusted executable paths, and provider argument arrays. Prompts are transported on stdin. Codex receives explicit sandbox/approval configuration on each invocation; Claude receives an explicit permission mode. Neither CLI is invoked through a shell wrapper.

`store.py` owns a local SQLite ledger. `BEGIN IMMEDIATE` protects queue claims and cancellation/finalization races. A partial unique index disallows two active jobs for the same provider/session. Claims exclude workspaces with a running or unresolved interrupted job. Schema version 1 is explicit; a newer schema is rejected instead of being overwritten.

`events.py` accepts only provider-level JSON event envelopes. A successful turn event AND successful process exit are necessary for `completed`. Permission denials, changed session identity, or missing completion envelopes require review. Recognized rate failures alone can request retry. No agent-generated/tool-generated text is interpreted as a scheduler instruction.

`worker.py` acquires a process-scoped kernel lock: flock on POSIX, a nonblocking byte-range lock on Windows. It runs one child at a time, keeping stdout/stderr separate. A temporary stdin file avoids shell interpolation and pipe backpressure for the initial prompt. The supervisor checks local cancellation, stop requests, timeout, and a log-size guard. Provider APIs are not polled by the supervisor.

`cli.py` makes registration, inspection, starting/stopping, and recovery explicit. `doctor` does only binary resolution and `--version`. `_demo_agent.py` is an isolated simulation fixture, not an alternate provider.

## Persistence and the exactly-once boundary

A job is marked running before spawning its child. A crash between claim and launch is indistinguishable from a crash after launch without a stronger provider-side idempotency protocol. Consequently, a new worker moves every interrupted running job to `needs_review` and does not automatically reclaim it. This deliberately sacrifices automatic recovery in favor of avoiding duplicate side effects.

There is no claim of exactly-once remote agent execution. Kernel locking plus the ledger prevents duplicate supervisor claims within one home, not duplicate processes launched by unrelated tools or other state directories. A model/tool operation may have committed side effects before the CLI reports a rate failure. Retrying resumes the saved session, not a transaction rollback.

Queued jobs survive reboot but no login/startup service is installed. When the user starts a worker again, nonexpired overdue jobs may run. Expired jobs never launch. Stop/cancel does not revert partial code changes.

## Retry policy

Default attempts: 3 total. Base delay: 900 seconds, doubled by previous attempts. A trusted numeric provider hint can only increase the delay. A job also has an absolute expiry and per-attempt timeout. Unknown errors and billing/authentication problems fail without retries. A terminal success ends scheduling rather than submitting endless continue prompts.

## State files

- `state.sqlite3`: plaintext job specs, timing/state, worker metadata, and cooperative stop request.
- `worker.lock`: OS-locked file; do not delete it to force a second worker.
- `worker.log`: detached supervisor lifecycle output.
- `logs/<job>-<attempt>.stdout.jsonl`: raw provider stdout.
- `logs/<job>-<attempt>.stderr.log`: raw provider stderr.
- `logs/<job>-<attempt>.meta.json`: launch metadata and argument array; prompt excluded.

Single-user local disks only. Multi-user or networked queue coordination is out of scope.
