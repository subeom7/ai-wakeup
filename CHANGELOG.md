# Changelog

## 0.1.0a1 — 2026-09-29

Initial independently written scheduled-resume alpha.

- Exact UUID/project enrollment for Codex and Claude Code; timezone-explicit and relative scheduling.
- Local SQLite state, preview/status/cancel, explicit foreground/background worker lifecycle.
- OS worker lock, active-session uniqueness, and review-gated workspace recovery after interruption.
- Conservative provider JSON-event parsing, bounded rate-limit retries, timeout/log guards.
- Per-attempt private local logs, CLI executable diagnostics, and credential-free simulation.
- English/Korean documentation, MIT license, security boundaries, and multi-OS CI definition.

Automatic discovery of external sessions, reset-time extraction, hooks/wrappers, native desktop UI, and login services are not included. Live-provider and Windows/macOS execution validation remain outstanding.
