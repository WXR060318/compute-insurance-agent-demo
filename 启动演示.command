#!/bin/bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
DEMO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "${DEMO_ROOT}"
DEMO_PORT="${DEMO_PORT:-8765}"
if [ -x .venv/bin/python ] && /usr/bin/curl --silent --fail --max-time 2 "http://127.0.0.1:${DEMO_PORT}/api/health" | .venv/bin/python -c 'import json,sys; assert json.load(sys.stdin).get("app") == "compute-insurance-demo"' >/dev/null 2>&1; then
  /usr/bin/open "http://127.0.0.1:${DEMO_PORT}"
  exit 0
fi
(
  for DEMO_ATTEMPT in $(seq 1 300); do
    if [ -x .venv/bin/python ] && /usr/bin/curl --silent --fail --max-time 2 "http://127.0.0.1:${DEMO_PORT}/api/health" | .venv/bin/python -c 'import json,sys; assert json.load(sys.stdin).get("app") == "compute-insurance-demo"' >/dev/null 2>&1; then
      /usr/bin/open "http://127.0.0.1:${DEMO_PORT}"
      exit 0
    fi
    sleep 1
  done
) &
DEMO_OPEN_PID=$!
trap 'kill "${DEMO_OPEN_PID}" 2>/dev/null || true' EXIT
bash scripts/start.sh
