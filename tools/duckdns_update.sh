#!/usr/bin/env bash
# Update DuckDNS A + AAAA for litpilot (or DUCKDNS_DOMAIN).
# Usage: ./tools/duckdns_update.sh
# Secrets: secrets/duckdns.env  (gitignored)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${DUCKDNS_ENV_FILE:-$ROOT/secrets/duckdns.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$ENV_FILE" && set +a
fi

DOMAIN="${DUCKDNS_DOMAIN:-litpilot}"
TOKEN="${DUCKDNS_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: DUCKDNS_TOKEN is empty." >&2
  echo "  Put DUCKDNS_TOKEN=… in secrets/duckdns.env (chmod 600)" >&2
  exit 2
fi

if [[ -n "${DUCKDNS_IPV4:-}" ]]; then
  IP4="$DUCKDNS_IPV4"
else
  IP4="$(curl -4 -fsS --max-time 10 https://api.ipify.org || true)"
fi
if [[ -z "$IP4" ]]; then
  echo "ERROR: could not detect public IPv4" >&2
  exit 1
fi

if [[ -n "${DUCKDNS_IPV6:-}" ]]; then
  IP6="$DUCKDNS_IPV6"
else
  IP6="$(curl -6 -fsS --max-time 10 https://api64.ipify.org 2>/dev/null || true)"
fi

# Prefer dual-stack when IPv6 is available (helps some mobile networks).
if [[ -n "$IP6" ]]; then
  URL="https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=${IP4}&ipv6=${IP6}&verbose=true"
else
  URL="https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=${IP4}&verbose=true"
fi
RESP="$(curl -fsS --max-time 15 "$URL" || true)"

echo "domain=${DOMAIN}.duckdns.org"
echo "ipv4=${IP4}"
echo "ipv6=${IP6:-"(none)"}"
echo "duckdns_response=${RESP}"

if [[ "$RESP" == KO* ]] || [[ -z "$RESP" ]]; then
  echo "ERROR: DuckDNS update failed." >&2
  exit 1
fi

sleep 1
echo -n "public_A="; dig +short A "${DOMAIN}.duckdns.org" @1.1.1.1 | head -1
echo -n "public_AAAA="; dig +short AAAA "${DOMAIN}.duckdns.org" @1.1.1.1 | head -1
# Local resolver may still show Pi-hole LAN override — that is correct on Wi‑Fi.
echo -n "local_resolver="; getent ahostsv4 "${DOMAIN}.duckdns.org" 2>/dev/null | awk '{print $1; exit}' || true
exit 0
