# Self-host LitPilot on this machine

Public URL: **https://litpilot.duckdns.org**

## Current machine facts

| Item | Value |
|------|--------|
| App | `127.0.0.1:7860` (loopback only) |
| LAN IP | `192.168.12.133` (reserve in router DHCP) |
| DuckDNS | `litpilot.duckdns.org` |
| Ports 80/443 | **Pi-hole** web UI (not LitPilot) |
| Public IP class | Often **CGNAT** (`172.58.x`) — home port-forward may never receive internet traffic |

## Security model (good crypto, light on the CPU)

| Layer | Choice | Why |
|-------|--------|-----|
| Browser ↔ edge | **TLS 1.2+** (Caddy or Cloudflare) | Real encryption for passwords/sessions |
| Edge ↔ app | HTTP on **127.0.0.1 only** | No extra TLS CPU on torch/embed path |
| App | `DEBUG=false`, Secure cookies, CSRF, HSTS | Already in LitPilot |
| Disk | SQLCipher **optional** | Skip unless you need stolen-disk protection; adds CPU on every DB op |
| DuckDNS token | `secrets/duckdns.env` only | Never in git |

You do **not** need to encrypt the database to have a “secure site.” HTTPS is the right place for that.

## 1. DuckDNS token + IP update

1. Log in at https://www.duckdns.org  
2. Copy your **token**  
3. On this machine:

```bash
cp secrets/duckdns.env.example secrets/duckdns.env
chmod 600 secrets/duckdns.env
# put: DUCKDNS_TOKEN=your-token-here
./tools/duckdns_update.sh
```

Enable auto-refresh (user systemd):

```bash
mkdir -p ~/.config/systemd/user
cp deploy/duckdns-update.service deploy/duckdns-update.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now duckdns-update.timer
systemctl --user list-timers | grep duckdns
```

## 2. Port-forward path (what we’re using)

Pi-hole owns **:80** and **:443** on this PC, so LitPilot TLS sits on **:8443**.
The router must map **public 443 → this PC 8443**.

### Already done on the PC

| Piece | Status |
|-------|--------|
| DuckDNS IP update | `./tools/duckdns_update.sh` → OK |
| Let’s Encrypt cert (DNS-01, DuckDNS) | `secrets/letsencrypt/.../litpilot.duckdns.org/` (expires ~90 days) |
| Caddy reverse proxy | listens **:8443**, TLS, proxies to `127.0.0.1:7860` |
| Local smoke | `https://127.0.0.1:8443/health` → healthy 4.4.0 |

Start / keep Caddy:

```bash
# one-shot
~/bin/caddy run --config ~/HealthDatabaseAccess/deploy/Caddyfile.portforward

# or user service
cp deploy/caddy-litpilot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now caddy-litpilot.service
```

Renew certs (monthly cron or timer):

```bash
./tools/renew_litpilot_cert.sh
```

### You must do on the router (`192.168.12.1`)

1. Log into the router admin page (often `http://192.168.12.1`).
2. Find **Port Forwarding** / **Virtual Server** / **NAT**.
3. Add a rule:

| Field | Value |
|-------|--------|
| Name | LitPilot |
| External / WAN port | **443** |
| Internal / LAN IP | **192.168.12.133** (this PC — set a DHCP reservation) |
| Internal port | **8443** |
| Protocol | **TCP** (or TCP+UDP if you want HTTP/3/QUIC) |

4. Save / apply. Disable any “AP isolation” / guest-network blocks if testing from LAN.
5. Optional: also forward **80** only if you later move Pi-hole — not required for LitPilot with DNS-01 certs.

### Test after the router rule

From a phone on **cellular data** (not home Wi‑Fi):

```text
https://litpilot.duckdns.org/health
```

Expect JSON: `{"status":"healthy","version":"4.4.0"}`.

From this PC (always works without the router):

```bash
curl -skS https://127.0.0.1:8443/health
```

### If external still times out after port-forward

Your public IP (`172.58.x`) is often **CGNAT** (carrier shares one public IP). Then **no home router rule can accept inbound 443**. Check with the ISP for a public IP / “bridge mode”, or use Cloudflare Tunnel (below) as fallback.

### Fallback — Cloudflare Tunnel (if CGNAT)

No router ports. TLS at Cloudflare.

```bash
cloudflared tunnel login
cloudflared tunnel create litpilot
# see deploy/cloudflared-config.example.yml
cloudflared tunnel run litpilot
```

## 3. Production uvicorn (no --reload)

```bash
cd ~/HealthDatabaseAccess
# .env already has DEBUG=false and PUBLIC_BASE_URL=https://litpilot.duckdns.org
./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 7860 --proxy-headers --forwarded-allow-ips=127.0.0.1
```

Or user service:

```bash
cp deploy/litpilot-uvicorn.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now litpilot-uvicorn.service
```

## 4. Smoke checklist

```bash
curl -sS http://127.0.0.1:7860/health
./tools/duckdns_update.sh
curl -sS https://litpilot.duckdns.org/health   # after tunnel or working forward
```

Expect: `{"status":"healthy","version":"4.4.0"}` and browser login works on HTTPS.
