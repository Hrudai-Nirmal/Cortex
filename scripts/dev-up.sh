#!/usr/bin/env bash
# Boot the local live-integration stack and start the API, worker, console, and app surfaces.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.cortex-data/run"
LOG_DIR="$RUN_DIR/logs"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

start_process() {
  local name="$1"
  shift
  local pid_file="$RUN_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"
  if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" >/dev/null 2>&1; then
    echo "$name already running with pid $(cat "$pid_file")"
    return
  fi
  nohup "$@" >"$log_file" 2>&1 &
  echo $! >"$pid_file"
  echo "started $name (pid $(cat "$pid_file"))"
}

require_command docker
require_command pnpm

if [ ! -x "$ROOT_DIR/.venv/bin/python" ] || [ ! -x "$ROOT_DIR/.venv/bin/alembic" ]; then
  echo "Python virtualenv is missing. Expected $ROOT_DIR/.venv with alembic installed." >&2
  exit 1
fi

mkdir -p "$LOG_DIR" "$ROOT_DIR/.cortex-data/object-storage"

cd "$ROOT_DIR"
docker compose up -d postgres ollama

for _ in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U cortex -d cortex >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

"$ROOT_DIR/.venv/bin/alembic" upgrade head

start_process api "$ROOT_DIR/.venv/bin/uvicorn" cortex.main:createApp --factory --app-dir apps/api --host 127.0.0.1 --port 8000
start_process worker "$ROOT_DIR/.venv/bin/python" -m cortex.worker
start_process console-web pnpm --dir apps/web dev:console
start_process query-web pnpm --dir apps/web dev:query

echo "Cortex API: http://127.0.0.1:8000"
echo "Cortex console: http://127.0.0.1:5173"
echo "Cortex app: http://127.0.0.1:5174"
