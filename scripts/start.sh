#!/bin/bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${DEMO_ROOT}"
DEMO_PORT="${DEMO_PORT:-8765}"
if [ ! -x .venv/bin/python ] || [ ! -d frontend/node_modules ]; then bash scripts/setup.sh; fi
if [ ! -f frontend/dist/index.html ]; then bash scripts/build.sh; fi
if /usr/bin/curl --silent --fail --max-time 2 "http://127.0.0.1:${DEMO_PORT}/api/health" | .venv/bin/python -c 'import json,sys; assert json.load(sys.stdin).get("app") == "compute-insurance-demo"' >/dev/null 2>&1; then
  echo "算力智保 Demo 已运行：http://127.0.0.1:${DEMO_PORT}"
  exit 0
fi
echo "算力智保 Demo：http://127.0.0.1:${DEMO_PORT}"
echo '演示数据仅保存在本机。按 Ctrl+C 停止服务。'
exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "${DEMO_PORT}"
