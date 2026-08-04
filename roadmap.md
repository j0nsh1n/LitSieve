# roadmap.md — LitPilot

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

## Phase 3 — Stabilize v4.3.x host
- Tasks:
  - Keep multi-library + student starting-point positioning
  - Storage quota, AI key AES-GCM, optional SQLCipher as deploy options
  - Deploy checklist: SECRET_KEY, optional SMTP, quota, tokens; `/health` 200
  - No teacher LMS / live-share expansion unless human reopens scope
- Complete when: deploy checklist documented **and** production-ish smoke
  passes: `DEBUG=false` + real `SECRET_KEY`, `GET /health` → 200
  (`status: healthy`). Public cloud is operator-owned — run the same smoke
  against that URL when you deploy (see `docs/DEPLOY.md`).
- Status: [x] 2026-08-03 — `docs/DEPLOY.md` + README link; production smoke
  verified. Live publicly at **https://www.litpilot.org**, self-hosted on the
  operator's desktop behind a Cloudflare Tunnel (TLS at Cloudflare; Uvicorn
  serves plain HTTP on loopback). No PaaS involved.

## Phase 4 — Operate a live instance
Shipping changed the risk profile: there are real accounts with real data on a
home desktop, and the link has been shared publicly.
- Tasks:
  - Cap total accounts (registration is open; per-account quota bounds disk per
    user but nothing bounds the number of users)
  - Back up `users.db` + `user_data/` — currently no backup story, and the
    machine is a single point of failure
  - Watch `logs/litpilot.log` after incidents (rotating; ~30 MB ceiling)
  - Keep the HF model cache warm so no student pays for a first download
- Complete when: an account cap (or invite gate) is enforced, a restore has been
  tested at least once from a backup, and the operator can answer "what happened
  at 14:05?" from the log file
- Status: [ ] in progress — logging landed 2026-08-04; cap and backups open

## Backlog (unscheduled)
- Make `pyright app` blocking in CI after clearing the current error backlog
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
