#!/usr/bin/env bash
# Nakatomi local install — one command to a working local stack.
#
# Usage:
#   ./install.sh                          # bring up Postgres + app with Docker Compose
#   ./install.sh --seed you@example.com   # also create a workspace + owner + api key
#   ./install.sh --native                 # run via pip + local Postgres (expects pg on :5432)
#   ./install.sh --dashboard              # enable the audit dashboard and open Chrome to it
#
set -euo pipefail

NAKATOMI_URL="${NAKATOMI_URL:-http://localhost:8000}"
MODE="docker"
SEED_EMAIL=""
OPEN_DASHBOARD="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed) SEED_EMAIL="${2:-}"; shift 2 ;;
    --native) MODE="native"; shift ;;
    --dashboard) OPEN_DASHBOARD="true"; shift ;;
    -h|--help)
      sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

log() { printf "\033[36m[nakatomi]\033[0m %s\n" "$*"; }
fail() { printf "\033[31m[nakatomi]\033[0m %s\n" "$*" >&2; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required but not installed"
}

bootstrap_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    # Generate a real secret key
    if command -v openssl >/dev/null 2>&1; then
      SK=$(openssl rand -hex 32)
      # portable sed -i
      if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s|^SECRET_KEY=.*|SECRET_KEY=$SK|" .env
      else
        sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SK|" .env
      fi
      log "wrote .env with a generated SECRET_KEY"
    else
      log "wrote .env (set SECRET_KEY before exposing to the internet)"
    fi
  fi
}

wait_for_health() {
  log "waiting for $NAKATOMI_URL/health ..."
  for i in $(seq 1 60); do
    if curl -fsS "$NAKATOMI_URL/health" >/dev/null 2>&1; then
      log "up."
      return 0
    fi
    sleep 1
  done
  fail "timed out waiting for $NAKATOMI_URL/health"
}

open_browser() {
  local url="$1"
  log "opening $url in your browser"
  if [[ "$(uname)" == "Darwin" ]]; then
    open -a "Google Chrome" "$url" 2>/dev/null || open "$url"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url"
  elif command -v start >/dev/null 2>&1; then
    start "$url"
  else
    log "(couldn't detect a browser launcher — open $url manually)"
  fi
}

start_docker() {
  require docker
  if ! docker compose version >/dev/null 2>&1; then
    fail "docker compose v2 is required (docker compose, not docker-compose)"
  fi
  bootstrap_env
  log "building and starting the stack via docker compose"
  if [[ "$OPEN_DASHBOARD" == "true" ]]; then
    DASHBOARD_ENABLED=true docker compose up -d --build
  else
    docker compose up -d --build
  fi
  wait_for_health
}

start_native() {
  require python3
  require pip3
  require psql
  bootstrap_env
  log "installing Python deps (use a venv if you prefer — see README)"
  pip3 install -r requirements.txt
  log "running migrations"
  alembic upgrade head
  log "starting uvicorn (Ctrl+C to stop)"
  if [[ "$OPEN_DASHBOARD" == "true" ]]; then
    DASHBOARD_ENABLED=true uvicorn app.main:app --reload &
  else
    uvicorn app.main:app --reload &
  fi
  UVICORN_PID=$!
  wait_for_health
  trap "kill $UVICORN_PID 2>/dev/null || true" EXIT
}

seed() {
  local email="$1"
  local pw
  pw=$(openssl rand -base64 24 | tr -d '=+/')
  local slug
  slug=$(echo "${email%@*}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]//g')
  [[ -z "$slug" ]] && slug="default"

  if [[ "$MODE" == "docker" ]]; then
    docker compose exec -T app python -m scripts.seed \
      --email "$email" --password "$pw" \
      --workspace-name "${slug^} Workspace" --workspace-slug "$slug"
  else
    python3 -m scripts.seed \
      --email "$email" --password "$pw" \
      --workspace-name "${slug^} Workspace" --workspace-slug "$slug"
  fi
  cat <<EOF

───────────────────────────────────────────────────
 Nakatomi is up at $NAKATOMI_URL
 Seeded user:  $email
 Password:     $pw        (save this)
 Workspace:    $slug
 API key:      (printed above — save this)
 API docs:     $NAKATOMI_URL/docs
 MCP endpoint: $NAKATOMI_URL/mcp
───────────────────────────────────────────────────

EOF
}

main() {
  if [[ "$MODE" == "native" ]]; then
    start_native
  else
    start_docker
  fi

  if [[ -n "$SEED_EMAIL" ]]; then
    seed "$SEED_EMAIL"
  fi

  if [[ "$OPEN_DASHBOARD" == "true" ]]; then
    open_browser "$NAKATOMI_URL/dashboard"
  fi
}

main "$@"
