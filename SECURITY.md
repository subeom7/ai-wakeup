# Security policy and threat boundaries

This is an experimental **local, single-user** supervisor. It is not a sandbox, credential vault, hardened multi-tenant queue, or permission broker.

## Boundaries

Only explicitly registered sessions are scheduled. The database stores the full UUID, resolved executable prefix, working directory, follow-up prompt, timing, permission choice, and bounded retry policy. The supervisor invokes that prefix without a shell and supplies the prompt through stdin. No automatic account/billing switch or security bypass flag is added.

The actual CLI, its project/user configuration, hooks, plugins, and tools still run with the user's authority. Plan-mode text instructions are not a sandbox. The executable path can change contents after registration. A hostile local process running as the same user can change scheduler state or executables. Those are not defended security boundaries in this alpha.

The worker's kernel lock and active-session ledger protect only one data directory. They do not discover every external Claude/Codex process, unsnooze instance, or another ai-wakeup home. Use a dedicated worktree and only one supervisor per session/worktree.

Process-tree termination is best effort. A crashed worker can leave an orphaned provider or tool process. The next worker marks interrupted jobs `needs_review` and blocks new work in the same workspace until an explicit acknowledgement. Never acknowledge before inspecting remaining processes and partial filesystem changes.

Retries are based only on top-level provider failure events. Model text, tool output, old transcript lines, generic stderr messages, login errors, and insufficient-quota errors do not authorize retries. Unknown event formats require review or fail closed. Providers can evolve their schemas; this design does not guarantee compatibility with every version.

## Data

No telemetry or remote listener is implemented. Scheduler prompts and provider logs are **plaintext** and can include sensitive code, paths, or secrets emitted by the provider. `status` does not include the stored prompt by default; `preview --show-prompt` does. Log rendering strips terminal control characters, not secrets. No credential files are read or copied by this scheduler. Launched CLIs inherit authentication-related environment variables unchanged; their billing behavior is outside the scheduler's guarantees.

Store state in a private user-owned directory. POSIX directories are tightened to 0700; database/log files use 0600. Windows relies on the parent profile ACL, which must be checked on a real machine. Shared/network filesystems are unsupported. No encrypted-at-rest storage or secure deletion is promised.

## Reporting

Do not include tokens, full raw transcripts, or private code in public issues. Use repository private vulnerability reporting when available, or contact the maintainer privately before disclosure. Sanitize reproduction cases and report OS, Python version, CLI versions, and the minimal fixture reproducing the issue.
