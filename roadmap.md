# roadmap.md — Literature Research Aide

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

## Phase 1 — Governance files adoption
- Tasks:
  - Commit tracked `agents.md`, `spec.md`, `roadmap.md`, `context.md`, `CHANGELOG.md`
  - Stop gitignoring `context.md`; structure it as state-only (no policy rules)
  - Align agent workflow to agents.md (no push/PR without explicit ask)
- Complete when: all five files tracked on the working branch; CI green;
  agents can resume from context.md handoff without reading gitignored secrets
- Status: [x] 2026-07-30 (local; push only when human asks)

## Phase 2 — Optional recovery email (in flight)
- Tasks:
  - Username separate from email; optional verified recovery address
  - SMTP-gated; Account UI and password-reset paths
  - Tests in `tests/test_email_recovery.py`
- Complete when: feature merged to main, tests green, CHANGELOG entry, SMTP
  documented in `.env.example` / README as needed
- Status: [~] branch `feat/optional-verified-email` (not yet assumed on main)

## Phase 3 — Stabilize v4.3.x host
- Tasks:
  - Keep multi-library + student starting-point positioning
  - Storage quota, AI key AES-GCM, optional SQLCipher as deploy options
  - No teacher LMS / live-share expansion unless human reopens scope
- Complete when: deploy checklist (SECRET_KEY, optional SMTP, quota, tokens)
  documented and a clean main deploy runs `/health` 200
- Status: [ ]

## Backlog (unscheduled)
- Make `pyright app` blocking in CI after clearing the current error backlog
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
