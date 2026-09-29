# Contributing

Use Python 3.11+ and run `python -m unittest discover -s tests -v` plus `python -m ai_wakeup demo` before a pull request. No API credentials are needed. Keep runtime dependencies at zero unless a design discussion justifies adding one.

For parser changes, add minimal sanitized provider-event fixtures and both positive and false-positive tests. Assistant/tool output must never become an automatic-retry instruction. For scheduling changes, test cancellation races, duplicate claims, expired schedules, and interruption recovery without waiting for actual quota windows.

Do not claim Windows/macOS or live-provider validation based on simulated tests. Record OS, Python version, exact CLI versions, commands, and what was actually observed. Never put auth files, full private transcripts, or API secrets into this repository or CI. The CI workflow must not call paid providers or require user credentials.

Keep automatic enrollment, hook installation, daemon startup, filesystem writes, and permission changes explicit. Do not add blanket approval bypass flags to make a smoke test pass. Changes to stored state require a schema migration strategy; do not silently replace a user's existing ledger.
