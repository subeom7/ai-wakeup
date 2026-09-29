# Development guidance

This repository contains ai-wakeup, a local scheduler, not an autonomous goal-completion engine. Before editing, read README.md and SECURITY.md.

Run:

    python -m unittest discover -s tests -v
    python -m ai_wakeup demo

Preserve the full-session-ID contract, explicit enrollment, shell=False argument arrays, stdin prompt transport, bounded retries, conservative error classification, and no-replay crash recovery. Do not add account switching, credential extraction, quota bypass, blanket permission bypass, automatic publishing, or hooks/services installed without consent.

Tests use _demo_agent.py and must not call real providers. Do not read authentication files. Keep logs and state outside the repository. Do not deploy or push without the user's explicit workflow authorization. Distinguish implemented features, simulated test results, and authenticated real-world verification in every release note.
