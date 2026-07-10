#!/usr/bin/env bash
# Local dev server with auto-reload on Python changes.
# Static/HTML/JS/CSS updates apply on browser refresh (no restart needed).
#
# Usage:
#   ./run_dev.sh
#   ./run_dev.sh 8080          # optional port
#
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-7860}"
VENV_PY="./venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing ./venv — create it or adjust VENV_PY in run_dev.sh" >&2
  exit 1
fi

# Prefer a stable SECRET_KEY so reloads don't log you out.
# Order: existing env → .env file → generate once into .env.local (gitignored).
if [[ -z "${SECRET_KEY:-}" ]]; then
  if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a && source .env && set +a
  fi
fi

if [[ -z "${SECRET_KEY:-}" && -f .env.local ]]; then
  # shellcheck disable=SC1091
  set -a && source .env.local && set +a
fi

if [[ -z "${SECRET_KEY:-}" ]]; then
  KEY="$("$VENV_PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  printf 'SECRET_KEY=%s\nDEBUG=true\n' "$KEY" > .env.local
  echo "Wrote stable SECRET_KEY to .env.local (gitignored)."
  # shellcheck disable=SC1091
  set -a && source .env.local && set +a
fi

export SECRET_KEY
export DEBUG="${DEBUG:-true}"

echo "Starting Literature Research Aide on http://127.0.0.1:${PORT}"
echo "  DEBUG=${DEBUG}"
echo "  --reload is on (Python file changes restart the server)"
echo "  CSS/JS/HTML: just refresh the browser"
echo ""

exec "$VENV_PY" -m uvicorn main:app \
  --host 127.0.0.1 \
  --port "$PORT" \
  --reload \
  --reload-include "*.py" \
  --reload-include "*.html" \
  --reload-include "*.css" \
  --reload-include "*.js"
