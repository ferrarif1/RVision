#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

API_BASE="${VISTRAL_API_BASE:-http://localhost:8000}"
echo "[info] api regression base: ${API_BASE}"
VISTRAL_API_BASE="$API_BASE" PYTHONPATH="$ROOT_DIR" python3 -m unittest discover -s backend/tests/api_regression -t . -p 'test_*.py' -v
