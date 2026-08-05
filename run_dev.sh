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
# Always DEBUG for local reload server so Secure cookies work on http://localhost,
# even if .env has DEBUG=false for the public host / tunnel process.
export DEBUG=true

# Isolate dev data from the live site by DEFAULT.
#
# This script runs from the repo, which is also the service's WorkingDirectory,
# so without these it opens the *production* accounts DB and paper libraries:
# a test fetch would write into a real student's library, and a stray click
# could change a real password. Two processes sharing one rotating log file
# also lose lines when it rolls over.
#
# Export any of these yourself to override (e.g. to reproduce a bug against
# real data on a copy).
export USERS_DB="${USERS_DB:-dev_users.db}"
export USER_DATA_DIR="${USER_DATA_DIR:-dev_data}"
export LOG_FILE="${LOG_FILE:-logs/dev.log}"

echo "Starting LitSieve on http://127.0.0.1:${PORT}"
echo "  DEBUG=${DEBUG} (forced for run_dev; public host should use DEBUG=false)"
echo "  --reload is on (Python file changes restart the server)"
echo "  CSS/JS/HTML: just refresh the browser"
echo "  data: USERS_DB=${USERS_DB}  USER_DATA_DIR=${USER_DATA_DIR}"
if [[ "$USERS_DB" == "users.db" || "$USER_DATA_DIR" == "user_data" ]]; then
  echo "  !! WARNING: pointed at LIVE data. Ctrl-C now unless that is deliberate."
fi
echo ""

# No --reload-include: those flags are silently ignored unless `watchfiles` is
# installed, and they are not needed anyway. Jinja reloads templates per render
# and static files are read from disk per request, so HTML/CSS/JS changes show
# up on a browser refresh with no server restart.
exec "$VENV_PY" -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port "$PORT" \
  --reload
