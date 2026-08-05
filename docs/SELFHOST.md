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

Day-to-day:

```bash
systemctl --user restart litsieve-uvicorn.service   # after a code change
systemctl --user stop    litsieve-uvicorn.service
journalctl --user -u litsieve-uvicorn -f            # live logs
tail -f logs/litsieve.log                           # same, rotating file
```

Notes:

- `Restart=always` brings it back from crashes *and* clean exits, with a
  5-restarts-in-5-minutes limit so a genuinely broken deploy stays visible
  rather than looping. Clear that state with
  `systemctl --user reset-failed litsieve-uvicorn.service`.
- One worker, deliberately: extra workers each load their own copy of torch and
  the embedding models (see [DEPLOY.md](DEPLOY.md)).
- The unit reads the gitignored `.env`; with `DEBUG=false` it will not start
  without `SECRET_KEY`.

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
