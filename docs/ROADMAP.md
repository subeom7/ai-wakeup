# Roadmap

## First acceptance gate: prove this alpha on the actual Windows machine

Run CI on Windows, macOS, and Linux. On a disposable git worktree, record exact installed provider versions and test successful read/plan-only resumption, an explicitly permitted small edit, permission denial, Unicode paths, terminal closure after detached start, worker cancellation, and recovery after interruption. Confirm that no alternate authentication route or unexpected paid fallback was selected. Real rate-limit recovery requires an actual suitable account/session; simulation is not evidence of that integration.

Keep the already-working scheduler for important overnight work until this gate is complete, and never run both schedulers against the same session.

## Next scoped release

Add opt-in enrollment around a newly launched official CLI process, using documented machine-readable events. Investigate an optional Claude StopFailure hook without rewriting unrelated user settings. Specify how reset timestamps are observed and validated; do not invent a timestamp from a percentage or parse arbitrary assistant prose as authority. Add fixture tests for each supported CLI version.

## Later

Session picker, clearer live terminal status, explicit one-click registration of an existing stopped session, notifications, live-provider compatibility matrix, richer diagnostic checks, optional OS-native background service, and platform-specific process lifetime handling. Credential vaults, account cycling, quota bypass, broad remote orchestration, and an unrestricted approval mode are not goals.
