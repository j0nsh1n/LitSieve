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
- Status: [x] 2026-07-30 (local commits may still need push when human asks)

## Phase 2 — Optional recovery email
- Tasks:
  - Username separate from email; optional verified recovery address
  - SMTP-gated; Account UI and password-reset paths
  - Tests in `tests/test_email_recovery.py`
  - SMTP smoke tool (`tools/send_test_email.py`); MailerSend verified locally
- Complete when: feature on main, human-confirmed send/recovery works, secrets
  only in gitignored `.env` / secret dumps, `.env.example` documents SMTP
- Status: [x] 2026-07-30 (PR #38 merged; SMTP confirmed working by human)

## Phase 3 — Stabilize v4.3.x host (current)
- Tasks:
  - Keep multi-library + student starting-point positioning
  - Storage quota, AI key AES-GCM, optional SQLCipher as deploy options
  - Deploy checklist: SECRET_KEY, optional SMTP, quota, tokens; `/health` 200
  - No teacher LMS / live-share expansion unless human reopens scope
- Complete when: deploy checklist documented and a clean main deploy runs
  `/health` 200 on the intended host
- Status: [ ] current focus

## Backlog (unscheduled)
- Make `pyright app` blocking in CI after clearing the current error backlog
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
