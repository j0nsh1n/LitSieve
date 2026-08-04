#!/usr/bin/env bash
# Renew Let's Encrypt cert for litpilot.duckdns.org (DNS-01 via DuckDNS).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
./venv/bin/certbot renew \
  --config-dir secrets/letsencrypt/config \
  --work-dir secrets/letsencrypt/work \
  --logs-dir secrets/letsencrypt/logs \
  --quiet
# Reload caddy if running
if pgrep -x caddy >/dev/null; then
  /home/jonathans/bin/caddy reload --config "$ROOT/deploy/Caddyfile.portforward" 2>/dev/null \
    || true
fi
