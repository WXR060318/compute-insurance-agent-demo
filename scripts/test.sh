#!/bin/bash
set -euo pipefail
DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${DEMO_ROOT}"
AI_MODE=offline .venv/bin/python -m pytest backend/tests -q
bash scripts/build.sh
