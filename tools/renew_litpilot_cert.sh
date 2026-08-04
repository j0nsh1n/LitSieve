#!/usr/bin/env bash
# Renew local Let's Encrypt certs used by optional Caddy (if present).
# Prefer Cloudflare-managed TLS for the public hostname (tunnel).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -d secrets/letsencrypt/config ]]; then
  echo "No local certbot config under secrets/letsencrypt/ — nothing to renew."
  exit 0
fi
./venv/bin/certbot renew \
  --config-dir secrets/letsencrypt/config \
  --work-dir secrets/letsencrypt/work \
  --logs-dir secrets/letsencrypt/logs \
  --quiet
if pgrep -x caddy >/dev/null; then
  /home/jonathans/bin/caddy reload --config "$ROOT/deploy/Caddyfile.privileged" 2>/dev/null \
    || /home/jonathans/bin/caddy reload --config "$ROOT/deploy/Caddyfile.portforward" 2>/dev/null \
    || true
fi
