#!/usr/bin/env bash
# Print the current Cloudflare quick-tunnel URL (if running).
set -euo pipefail
URL="$(journalctl --user -u cloudflared-quick.service -n 80 --no-pager 2>/dev/null \
  | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)"
if [[ -z "$URL" ]]; then
  # fallback: process log if any
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf-litpilot.log 2>/dev/null | tail -1 || true)"
fi
if [[ -z "$URL" ]]; then
  echo "No tunnel URL found. Start with:"
  echo "  systemctl --user enable --now cloudflared-quick.service"
  exit 1
fi
echo "$URL"
echo "health: $URL/health"
curl -fsS --max-time 15 "$URL/health" 2>/dev/null && echo || true
