#!/usr/bin/env bash
# One-time: allow Caddy to bind ports 80/443 without running as root.
set -euo pipefail
CADDY="${HOME}/bin/caddy"
ROOT="${HOME}/HealthDatabaseAccess"
if [[ ! -x "$CADDY" ]]; then
  echo "Missing $CADDY" >&2
  exit 1
fi
echo "Granting cap_net_bind_service to $CADDY (sudo password)..."
sudo setcap 'cap_net_bind_service=+ep' "$CADDY"
getcap "$CADDY"
# Switch service to privileged Caddyfile
sed -i 's|Caddyfile.portforward|Caddyfile.privileged|' \
  "$HOME/.config/systemd/user/caddy-litpilot.service" 2>/dev/null || true
# Also update unit file in repo deploy copy used if re-copied
sed -i 's|Caddyfile.portforward|Caddyfile.privileged|g' \
  "$ROOT/deploy/caddy-litpilot.service"
systemctl --user daemon-reload
systemctl --user restart caddy-litpilot.service
sleep 1
systemctl --user --no-pager status caddy-litpilot.service | head -15
ss -tlnp | grep -E ':80 |:443 ' || true
curl -skS https://127.0.0.1/health; echo
echo "OK — router should forward WAN 443 → 192.168.12.133:443"
