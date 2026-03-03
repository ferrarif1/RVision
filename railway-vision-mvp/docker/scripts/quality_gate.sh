#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "[info] quality gate: compile checks"
python -m compileall "${ROOT_DIR}/backend/app" "${ROOT_DIR}/edge/agent" "${ROOT_DIR}/edge/inference" >/tmp/rv_quality_compile.log
tail -n 8 /tmp/rv_quality_compile.log

echo "[info] quality gate: golden plugin fixtures"
PYTHONPATH="${ROOT_DIR}/edge" python -m inference.golden_checks

echo "[info] quality gate: backend health (optional)"
if curl -ksSf https://localhost:8443/api/health >/dev/null 2>&1; then
  echo "[ok] backend health endpoint reachable via frontend gateway"
else
  echo "[warn] health endpoint not reachable at https://localhost:8443/api/health"
  echo "[warn] start docker compose before full runtime checks"
fi

echo "[ok] quality gate passed"
