#!/usr/bin/env bash
# One-time setup helper for a named Cloudflare Tunnel (LitSieve on loopback).
# T-Mobile Home Internet / CGNAT: use a tunnel instead of port-forwarding.
#
# Prefer the dashboard "Install with token" flow. This script is for
# cert/config-file based tunnels.
#
# Usage: ./tools/setup_cloudflare_tunnel.sh
set -euo pipefail

CF="${CLOUDFLARED:-cloudflared}"
command -v "$CF" >/dev/null || CF=/usr/local/bin/cloudflared
command -v "$CF" >/dev/null || { echo "Install cloudflared first"; exit 1; }

echo "=== 1) Login (browser will open) ==="
"$CF" tunnel login

echo "=== 2) Create named tunnel 'litsieve' (ok if exists) ==="
"$CF" tunnel create litsieve 2>/dev/null || "$CF" tunnel list

TUNNEL_ID="$("$CF" tunnel list -o json 2>/dev/null | python3 -c '
import json,sys
data=json.load(sys.stdin)
for t in data:
    if t.get("name")=="litsieve":
        print(t["id"]); break
' 2>/dev/null || true)"

if [[ -z "${TUNNEL_ID}" ]]; then
  TUNNEL_ID="$("$CF" tunnel list | awk '/litsieve/{print $1; exit}')"
fi
echo "tunnel_id=${TUNNEL_ID}"

CREDS="${HOME}/.cloudflared/${TUNNEL_ID}.json"
if [[ ! -f "$CREDS" ]]; then
  CREDS="$(ls -1 "${HOME}/.cloudflared/"*.json 2>/dev/null | head -1 || true)"
fi
echo "credentials=${CREDS}"

mkdir -p "${HOME}/.cloudflared"
cat > "${HOME}/.cloudflared/config.yml" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CREDS}

ingress:
  - service: http://127.0.0.1:7860
EOF

echo
echo "Config: ~/.cloudflared/config.yml"
echo "Next:"
echo "  1. Cloudflare Zero Trust → Networks → Tunnels → Public Hostname"
echo "  2. Hostname: YOUR_DOMAIN (domain on your Cloudflare account)"
echo "  3. Service: http://127.0.0.1:7860"
echo "  4. App .env: PUBLIC_BASE_URL=https://YOUR_DOMAIN  DEBUG=false"
echo "  5. systemctl --user enable --now cloudflared-litpilot-token.service"
echo "     (token install) or: cloudflared tunnel run"
