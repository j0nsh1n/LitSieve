# Self-host LitPilot

Public access on T‑Mobile Home Internet uses a **Cloudflare Tunnel** (inbound
port-forwarding is not available / CGNAT). TLS for visitors is terminated at
Cloudflare; this PC only serves LitPilot on loopback.

## Machine layout

| Piece | Role |
|-------|------|
| LitPilot | `uvicorn` on `127.0.0.1:7860` only |
| `cloudflared` | Outbound tunnel to Cloudflare (token or config) |
| Caddy (optional) | LAN HTTPS on :80/:443 if you want local TLS without the tunnel |
| Pi-hole | Admin on high ports (e.g. 8080 / 8444) if still installed |

## Required app env (gitignored `.env`)

```bash
DEBUG=false
PUBLIC_BASE_URL=https://YOUR_DOMAIN
# SECRET_KEY=…  required when DEBUG=false
# SMTP_* optional — recovery links use PUBLIC_BASE_URL
```

`YOUR_DOMAIN` is the hostname you attach in the Cloudflare tunnel **Public
Hostname** settings (the domain you bought and pointed at Cloudflare).

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
   - Hostname: `YOUR_DOMAIN` (or `www` / subdomain)
   - Service: **HTTP** → `http://127.0.0.1:7860`

6. Keep LitPilot running:

   ```bash
   ./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 7860
   # or: systemctl --user enable --now litpilot-uvicorn.service
   ```

### Smoke

```bash
curl -sS http://127.0.0.1:7860/health
# After DNS for YOUR_DOMAIN points via Cloudflare:
curl -sS https://YOUR_DOMAIN/health
```

## Optional: Caddy on the LAN

If you still want HTTPS on the LAN IP/name without going through Cloudflare,
see `deploy/Caddyfile.privileged` (needs `cap_net_bind_service` for :80/:443).
Prefer certificates for **YOUR_DOMAIN** (HTTP-01 or DNS-01 via your DNS host),
not legacy providers.

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
