# Self-host LitSieve

Generic runbook for an operator-owned host. Paths and unit names below match
the examples under `deploy/`; rename if your install differs.

## Architecture

```text
Browser  --HTTPS-->  Cloudflare  --HTTP-->  cloudflared  --HTTP-->  uvicorn
                     (TLS at edge)           (origin host)         127.0.0.1:7860
```

| Edge | Origin |
|------|--------|
| **Public URL** (example) | `https://www.litpilot.org` |
| **Local FastAPI** | `http://127.0.0.1:7860` only (no TLS on Uvicorn) |

Cloudflare Tunnel **terminates HTTPS**. Do **not** give Uvicorn certificates or
`--ssl-keyfile` / `--ssl-certfile`. Optional Caddy is only for LAN experiments,
not for the public hostname.

Use a tunnel (or similar outbound connector) whenever the host is behind CGNAT
or has no stable inbound ports — do not depend on ISP port-forward.

## Machine layout

| Piece | Role |
|-------|------|
| LitSieve | `uvicorn` **HTTP** on `127.0.0.1:7860` only |
| `cloudflared` | Outbound tunnel; public hostname → origin HTTP |
| Caddy (optional) | LAN-only reverse proxy — not required for the public hostname |

## Required app env (gitignored `.env`)

```bash
DEBUG=false
PUBLIC_BASE_URL=https://www.example.com   # your public HTTPS origin
# SECRET_KEY=…  required when DEBUG=false
# SMTP_* optional — recovery links use PUBLIC_BASE_URL
```

Point the tunnel at **`http://127.0.0.1:7860`**. Set `PUBLIC_BASE_URL` to the
HTTPS URL users type in the browser.

## Cloudflare Tunnel

1. Install `cloudflared` (package or binary).
2. Create a tunnel in Zero Trust / Cloudflare dashboard; copy the token.
3. Store the token only in a gitignored file, e.g.:

   ```bash
   # secrets/cloudflared.env  (chmod 600, never commit)
   TUNNEL_TOKEN=…
   ```

4. Run with a user service (example unit in `deploy/`):

   ```bash
   systemctl --user enable --now cloudflared-litpilot-token.service
   systemctl --user status cloudflared-litpilot-token.service
   ```

5. In the dashboard, add a **Public Hostname**:
   - Hostname: your public name (e.g. `www` + your domain)
   - Service: **HTTP** → `http://127.0.0.1:7860`
   - Optional: apex hostname → same service (or redirect to www)

6. Keep LitSieve running (see **Run it as a service** — do not leave it only
   in a terminal session).

## Run it as a service (starts at boot)

Running `uvicorn` in a terminal means the site dies when that session ends, does
not restart if it crashes, and does not come back after a reboot. Install the
unit instead — same idea as the tunnel service.

```bash
# From the repo root on the origin host:
mkdir -p ~/.config/systemd/user
cp deploy/litsieve-uvicorn.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now litsieve-uvicorn.service
systemctl --user status litsieve-uvicorn.service
```

**Linger** makes user services survive logout and start at boot:

```bash
loginctl show-user "$USER" --property=Linger   # want Linger=yes
sudo loginctl enable-linger "$USER"
```

Switching over from a manually started server: stop the old process first, or
the service will fail with "address already in use".

```bash
ss -ltnp | grep 7860
systemctl --user start litsieve-uvicorn.service
curl -sS http://127.0.0.1:7860/health
```

See [Everyday commands](#everyday-commands) below for the day-to-day loop.

Notes:

- `Restart=always` brings it back from crashes *and* clean exits, with a
  5-restarts-in-5-minutes limit so a genuinely broken deploy stays visible
  rather than looping. Clear that state with
  `systemctl --user reset-failed litsieve-uvicorn.service`.
- One worker, deliberately: extra workers each load their own copy of torch and
  the embedding models (see [DEPLOY.md](DEPLOY.md)).
- The unit reads the gitignored `.env`; with `DEBUG=false` it will not start
  without `SECRET_KEY`.

## Everyday commands

Run these from the **repo root** on the origin host.

### After a reboot — nothing

If the service is `enabled` and the account has `Linger=yes`, it starts on its
own. Confirm if you want:

```bash
systemctl --user status litsieve-uvicorn.service
curl -sS http://127.0.0.1:7860/health     # {"status":"healthy","version":"…"}
```

Prefer the **local** URL for health checks. Some edges (including Cloudflare
managed challenges) return 403 to bare `curl` against the public hostname even
when the app is healthy — that is not a reliable up/down signal by itself.

### After changing code

The service runs whatever was on disk when it started; it does not notice edits.

```bash
SECRET_KEY=x DEBUG=true ./venv/bin/python -m pytest -q   # optional, but cheap
systemctl --user restart litsieve-uvicorn.service
curl -sS http://127.0.0.1:7860/health
```

A couple of seconds of downtime. Skipping the tests risks restarting a public
site into a broken state.

### While developing

```bash
./run_dev.sh 7861
```

Auto-reloads on save, on a spare port, against **throwaway data**
(`dev_users.db`, `dev_data/`, `logs/dev.log`) so a live process on 7860 can keep
its accounts and libraries untouched. The script prints which stores it is using
and warns if you override it back onto live data.

Note it forces `DEBUG=true`, so cookies are not `Secure` and reset codes may
render on screen. Correct for `http://localhost`, but the dev server is not a
faithful test of the production auth path.

### When something looks wrong

```bash
systemctl --user status  litsieve-uvicorn.service
journalctl --user -u litsieve-uvicorn -n 50 --no-pager   # recent
journalctl --user -u litsieve-uvicorn -f                 # live
tail -f logs/litsieve.log                                # same + access lines
```

Service will not start? Usually one of:

- something else still holds 7860 — `ss -ltnp | grep 7860`
- `SECRET_KEY` missing from `.env` — with `DEBUG=false` the app refuses to boot
- crash-looping past the limit — `systemctl --user reset-failed litsieve-uvicorn.service`

## Watchdog (know when it breaks)

A tunnel unit can show `active` while the public edge is dead (for example after
a token revoke that only fails on the next reconnect). Local `/health` can also
look fine while the tunnel has no registered connections.

`tools/watchdog.py` checks both signals the operator actually cares about — the
app answers locally, and the tunnel currently holds registered connections —
and emails on **state changes** (not every poll).

Install:

```bash
cp deploy/litsieve-watchdog.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now litsieve-watchdog.timer
```

**Add the recipient to `.env`, or alerts are silently skipped:**

```bash
WATCHDOG_EMAIL_TO=you@example.com
```

It reuses the app's existing `SMTP_*` settings. Check and tune:

```bash
systemctl --user list-timers litsieve-watchdog.timer     # next run
./venv/bin/python tools/watchdog.py --no-email           # run by hand
journalctl --user -u litsieve-watchdog -n 20 --no-pager
cat logs/watchdog_state.json                             # last known state
```

| Variable | Default | Meaning |
|----------|---------|---------|
| `WATCHDOG_EMAIL_TO` | *(unset)* | Alert recipient. Unset = no email. |
| `WATCHDOG_REMIND_HOURS` | `12` | Re-send while still down. `0` = once only. |
| `WATCHDOG_HEALTH_URL` | `http://127.0.0.1:7860/health` | App check |
| `WATCHDOG_TUNNEL_UNIT` | `cloudflared-litpilot-token` | Tunnel unit to inspect (rename if needed) |

Exit codes: `0` healthy, `1` down (already emailed), `2` the check itself could
not run. The unit treats `1` as success so a genuine outage does not also show
up as a failed unit.

## Backups

On a single-machine deploy, `users.db` and `user_data/` are a single point of
failure: accounts, libraries, embeddings, notes, and screening decisions.

`tools/backup.py` runs daily via `litsieve-backup.timer` and writes under
`BACKUP_DIR` (default `~/litsieve-backups/`) — deliberately **outside** the
repo so a bad deploy or `git clean` cannot delete archives with the code tree.

```bash
cp deploy/litsieve-backup.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now litsieve-backup.timer

tools/backup.py --list                 # what exists
tools/backup.py                        # run one now
tools/backup.py --verify <archive>     # integrity-check an archive
systemctl --user list-timers litsieve-backup.timer
```

Two things make this more than `cp -r`:

- Databases are copied through the **SQLite online backup API**, not the
  filesystem. They run in WAL mode with a live server attached, so a plain copy
  can catch a torn write and restore to a corrupt file.
- Every copy is **integrity-checked before the archive is written**, and the
  archive is re-verified afterwards. An unverified backup is a guess.

| Variable | Default | Meaning |
|----------|---------|---------|
| `BACKUP_DIR` | `~/litsieve-backups` | Where archives are written |
| `BACKUP_KEEP` | `14` | Archives retained; older ones pruned |

**The archive contains every user's data and, by default, `.env` — including
`SECRET_KEY`.** That is deliberate: without it, stored AI keys cannot be
decrypted, so a restore would be partial. Archives are written `0600`. Use
`--no-env` to exclude it, and encrypt any copy you move off the machine.

### Restoring

```bash
# REPO = path to the LitSieve checkout on the origin host
tar -xzf ~/litsieve-backups/litsieve-YYYYMMDD-HHMMSS.tar.gz -C /tmp/restore
systemctl --user stop litsieve-uvicorn.service
cp /tmp/restore/litsieve/users.db "$REPO/"
cp -r /tmp/restore/litsieve/user_data "$REPO/"
systemctl --user start litsieve-uvicorn.service
```

Off-machine copies remain the operator’s job: local archives protect against a
bad deploy, accidental delete, or filesystem corruption — not against total
loss of the host disk. Copy the newest archive somewhere else periodically.

### Smoke

```bash
curl -sS http://127.0.0.1:7860/health
# Public URL may return edge challenge responses to curl; prefer local /health.
```

## Optional: Caddy on the LAN

If you want HTTPS on the LAN without going through Cloudflare, see
`deploy/Caddyfile.privileged` (needs `cap_net_bind_service` for :80/:443).

## Security (good crypto, light on the CPU)

| Layer | Choice |
|-------|--------|
| Browser ↔ Cloudflare | TLS 1.2+ at the edge |
| Cloudflare ↔ app | HTTP on `127.0.0.1` only |
| App | `DEBUG=false`, Secure cookies, CSRF, HSTS |
| Disk encryption | Optional SQLCipher — skip unless you need stolen-disk protection |

## Efficiency on one machine

- One uvicorn worker (do not multi-worker torch)
- `MAX_LOADED_MODELS=3` (shared embedding registry)
- No `--reload` for the public process
- Bind app to `127.0.0.1` only
