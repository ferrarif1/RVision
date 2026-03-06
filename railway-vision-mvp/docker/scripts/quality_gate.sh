#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "[info] quality gate: compile checks"
python -m compileall "${ROOT_DIR}/backend/app" "${ROOT_DIR}/edge/agent" "${ROOT_DIR}/edge/inference" >/tmp/rv_quality_compile.log
tail -n 8 /tmp/rv_quality_compile.log

echo "[info] quality gate: schema snapshot guard"
python3 "${ROOT_DIR}/docker/scripts/schema_snapshot_guard.py"

echo "[info] quality gate: golden plugin fixtures"
PYTHONPATH="${ROOT_DIR}/edge" python -m inference.golden_checks

echo "[info] quality gate: backend health (optional)"
if curl -ksSf https://localhost:8443/api/health >/dev/null 2>&1; then
  echo "[ok] backend health endpoint reachable via frontend gateway"
elif curl -sSf http://localhost:8000/health >/dev/null 2>&1; then
  echo "[ok] backend health endpoint reachable at http://localhost:8000/health"
else
  echo "[warn] health endpoint not reachable at https://localhost:8443/api/health"
  echo "[warn] start docker compose before full runtime checks"
  echo "[warn] training control plane smoke skipped"
  echo "[ok] quality gate passed"
  exit 0
fi

echo "[info] quality gate: runtime hardening smoke"
python3 "${ROOT_DIR}/docker/scripts/runtime_hardening_smoke.py"

echo "[info] quality gate: quick detect smoke"
python3 "${ROOT_DIR}/docker/scripts/quick_detect_smoke.py"

echo "[info] quality gate: training control plane smoke"
python3 "${ROOT_DIR}/docker/scripts/training_control_plane_smoke.py"

echo "[ok] quality gate passed"
