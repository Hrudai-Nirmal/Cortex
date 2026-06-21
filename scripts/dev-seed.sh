#!/usr/bin/env bash
# Seed the deterministic live-integration fixture corpus through the running API.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v curl >/dev/null 2>&1; then
  echo "Missing required command: curl" >&2
  exit 1
fi

curl \
  --fail \
  --silent \
  --show-error \
  -H "Authorization: Bearer fixture-admin" \
  -X POST "http://127.0.0.1:8000/v1/dev/seed"
echo
