#!/usr/bin/env bash
# One-time setup: Cloudflare Tunnel so LitPilot is reachable off your home LAN
# (T-Mobile Home Internet cannot do real port-forwarding / is on CGNAT).
#
# You need a free Cloudflare account. DuckDNS cannot CNAME to a tunnel, so we
# either:
#   A) Use a free hostname Cloudflare gives you for the tunnel, or
#   B) Add any domain you control to Cloudflare and attach litpilot.<domain>
#
# Usage:
#   ./tools/setup_cloudflare_tunnel.sh
set -euo pipefail

CF="${CLOUDFLARED:-cloudflared}"
command -v "$CF" >/dev/null || CF=/usr/local/bin/cloudflared
command -v "$CF" >/dev/null || { echo "Install cloudflared first"; exit 1; }

echo "=== 1) Login (browser will open) ==="
"$CF" tunnel login

echo "=== 2) Create named tunnel 'litpilot' (ok if exists) ==="
"$CF" tunnel create litpilot 2>/dev/null || "$CF" tunnel list

TUNNEL_ID="$("$CF" tunnel list -o json 2>/dev/null | python3 -c '
import json,sys
data=json.load(sys.stdin)
for t in data:
    if t.get("name")=="litpilot":
        print(t["id"]); break
' 2>/dev/null || true)"

if [[ -z "${TUNNEL_ID}" ]]; then
  # fallback parse table
  TUNNEL_ID="$("$CF" tunnel list | awk '/litpilot/{print $1; exit}')"
fi
echo "tunnel_id=${TUNNEL_ID}"

CREDS="${HOME}/.cloudflared/${TUNNEL_ID}.json"
if [[ ! -f "$CREDS" ]]; then
  # credentials file name variants
  CREDS="$(ls -1 "${HOME}/.cloudflared/"*.json 2>/dev/null | head -1 || true)"
fi
echo "credentials=${CREDS}"

mkdir -p "${HOME}/.cloudflared"
cat > "${HOME}/.cloudflared/config.yml" <<EOF
# LitPilot — outbound-only tunnel (works on T-Mobile CGNAT)
tunnel: ${TUNNEL_ID}
credentials-file: ${CREDS}

ingress:
  # Prefer a hostname you add in Zero Trust → Networks → Tunnels → Public hostname
  # (requires a domain on your Cloudflare account). Until then, any request that
  # reaches this tunnel is sent to the app:
  - service: http://127.0.0.1:7860
EOF

echo
echo "=== 3) Config written to ~/.cloudflared/config.yml ==="
echo "Next:"
echo "  1. Open https://one.dash.cloudflare.com/ → Zero Trust → Networks → Tunnels"
echo "  2. Select tunnel 'litpilot' → Public Hostname → Add"
echo "     Service: http://127.0.0.1:7860"
echo "     (If you have no domain on Cloudflare yet, add a free/cheap domain there,"
echo "      or use the temporary URL from: cloudflared tunnel --url http://127.0.0.1:7860)"
echo "  3. Enable user service:"
echo "       cp deploy/cloudflared-litpilot.service ~/.config/systemd/user/"
echo "       # fix cloudflared path if needed"
echo "       systemctl --user daemon-reload"
echo "       systemctl --user enable --now cloudflared-litpilot.service"
echo
echo "DuckDNS name stays for HOME (Pi-hole Local DNS → 192.168.12.133)."
echo "Off-network access uses the Cloudflare hostname (T-Mobile cannot open 443)."
echo
echo "Test tunnel now (Ctrl+C to stop):"
echo "  $CF tunnel --config ${HOME}/.cloudflared/config.yml run"
