# Self-host LitSieve

## Architecture (do not change)

```text
Browser  --HTTPS-->  Cloudflare  --HTTP-->  cloudflared  --HTTP-->  uvicorn
                     (TLS here)              (this PC)              127.0.0.1:7860
```

| Edge | Origin |
|------|--------|
| **Public URL** | `https://www.litpilot.org` |
| **Local FastAPI** | `http://127.0.0.1:7860` only (no TLS on Uvicorn) |

Cloudflare Tunnel **terminates HTTPS**. Do **not** give Uvicorn certificates or
`--ssl-keyfile` / `--ssl-certfile`. Optional Caddy is only for LAN experiments,
not for the public hostname.

Public access on T‑Mobile Home Internet uses the tunnel (CGNAT; no inbound
port-forward).

## Machine layout

| Piece | Role |
|-------|------|
| LitSieve | `uvicorn` **HTTP** on `127.0.0.1:7860` only |
| `cloudflared` | Outbound tunnel; public hostname `www.litpilot.org` → origin |
| Caddy (optional) | LAN-only reverse proxy — not required for www.litpilot.org |
| Pi-hole | Admin on high ports (e.g. 8080 / 8444) if still installed |

## Required app env (gitignored `.env`)

```bash
DEBUG=false
PUBLIC_BASE_URL=https://www.litpilot.org
# SECRET_KEY=…  required when DEBUG=false
# SMTP_* optional — recovery links use PUBLIC_BASE_URL
```

Public hostname: **`www.litpilot.org`** (Cloudflare Tunnel → `http://127.0.0.1:7860`).

## Cloudflare Tunnel

1. Install `cloudflared` (package or binary).
2. Create a tunnel in Zero Trust / Cloudflare dashboard; copy the token.
3. Store the token only in a gitignored file, e.g.:

   ```bash
   # secrets/cloudflared.env  (chmod 600, never commit)
   TUNNEL_TOKEN=…
   ```

4. Run with the user service (example):

   ```bash
   systemctl --user enable --now cloudflared-litpilot-token.service
   systemctl --user status cloudflared-litpilot-token.service
   ```

5. In the dashboard, add a **Public Hostname**:
   - Subdomain: `www`
   - Domain: `litpilot.org`
   - Service: **HTTP** → `http://127.0.0.1:7860`
   - Optional second rule: apex `litpilot.org` → same service (or redirect to www)

6. Keep LitSieve running (see **Run it as a service** below — do not leave it
   running in a terminal, it dies with the session).

## Run it as a service (starts at boot)

Running `uvicorn` in a terminal means the site dies when that session ends, does
not restart if it crashes, and does not come back after a reboot. Install the
unit instead — the same way `cloudflared` already runs.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/litsieve-uvicorn.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now litsieve-uvicorn.service
systemctl --user status litsieve-uvicorn.service
```

**Linger** is what makes user services survive logout and start at boot. It is
already enabled on this host (cloudflared needs it too), but on a fresh machine:

```bash
loginctl show-user "$USER" --property=Linger   # want Linger=yes
sudo loginctl enable-linger "$USER"
```

Switching over from a manually started server: stop the old process first, or
the service will fail with "address already in use".

```bash
# find whatever is holding 7860, then stop it
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

The four things you actually do. Run them from `~/HealthDatabaseAccess`.

### After a reboot — nothing

The service is `enabled` and the account has `Linger=yes`, so it starts on its
own. Confirm if you want:

```bash
systemctl --user status litsieve-uvicorn.service
curl -sS http://127.0.0.1:7860/health     # {"status":"healthy","version":"…"}
```

Check the *local* URL, not the public one: Cloudflare serves a managed
challenge, so `curl https://www.litpilot.org/health` returns 403
(`cf-mitigated: challenge`) even when the site is perfectly healthy.

### After changing code

The service runs whatever was on disk when it started; it does not notice edits.

```bash
SECRET_KEY=x DEBUG=true ./venv/bin/python -m pytest -q   # optional, but cheap
systemctl --user restart litsieve-uvicorn.service
curl -sS http://127.0.0.1:7860/health
```

A couple of seconds of downtime. Skipping the tests risks restarting the public
site into a broken state.

### While developing

```bash
./run_dev.sh 7861
```

Auto-reloads on save, on a spare port, against **throwaway data**
(`dev_users.db`, `dev_data/`, `logs/dev.log`) — the live site on 7860 keeps
running and its accounts and libraries are untouched. The script prints which
stores it is using and warns if you override it back onto live data.

Note it forces `DEBUG=true`, so cookies are not `Secure` and reset codes may
render on screen. Correct for `http://localhost`, but it means the dev server is
not a faithful test of the production auth path.

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

On 2026-08-05 the site was down for **4h47m** and nothing said so. The tunnel
token had been revoked the day before, but cloudflared never re-authenticates an
*already established* connection — so the site kept serving until the machine's
unattended ~05:01 reboot forced a fresh registration, which failed. Every signal
looked healthy: the tunnel unit was `active`, the app answered `/health` 200,
and `curl` against the public hostname returns 403 either way.

`tools/watchdog.py` checks the two things that actually distinguish up from
down — the app answers locally, and the tunnel currently holds registered
connections — and emails on state changes (not every poll).

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

It reuses the app's existing `SMTP_*` settings, so there is nothing else to
configure. Check and tune:

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
| `WATCHDOG_TUNNEL_UNIT` | `cloudflared-litpilot-token` | Tunnel unit to inspect |

Exit codes: `0` healthy, `1` down (already emailed), `2` the check itself could
not run. The unit treats `1` as success so a genuine outage does not also show
up as a failed unit.

### Smoke

```bash
curl -sS http://127.0.0.1:7860/health
curl -sS https://www.litpilot.org/health
```

## Optional: Caddy on the LAN

If you still want HTTPS on the LAN without going through Cloudflare, see
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
