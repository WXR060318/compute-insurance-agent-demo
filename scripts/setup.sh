#!/bin/bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${DEMO_ROOT}"
if command -v python3.12 >/dev/null 2>&1; then
  DEMO_PYTHON="$(command -v python3.12)"
else
  DEMO_PYTHON="$(command -v python3)"
fi
"${DEMO_PYTHON}" -c 'import sys; assert sys.version_info >= (3,11), "需要 Python 3.11 或更高版本"'
command -v npm >/dev/null 2>&1 || { echo '请先安装 Node.js 与 npm。'; exit 1; }
if [ ! -x .venv/bin/python ]; then "${DEMO_PYTHON}" -m venv .venv; fi
.venv/bin/python -m pip install -r backend/requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
cd frontend
if [ -f package-lock.json ]; then npm ci; else npm install; fi
echo '依赖已准备好。'
