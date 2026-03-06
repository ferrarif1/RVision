#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/docker/.env"

MODEL_FILE="$ROOT_DIR/backend/app/uploads/open_models/mobilenet_ssd_bundle.zip"
MODEL_ID="${MODEL_ID:-object_detect}"
TASK_TYPE="${TASK_TYPE:-$MODEL_ID}"
PLUGIN_NAME="${PLUGIN_NAME:-$TASK_TYPE}"
VERSION="${VERSION:-v1.0.0-open}"
OUTPUT_NAME="${OUTPUT_NAME:-${MODEL_ID}_open_model_package.zip}"
OUTPUT_ZIP="/app/app/uploads/${OUTPUT_NAME}"

if [[ ! -f "$MODEL_FILE" ]]; then
  echo "[info] open model not found, downloading..."
  python3 "$ROOT_DIR/docker/scripts/download_open_model.py" --output "$MODEL_FILE"
fi

COMPOSE_CMD=(docker compose)
if [[ -f "$ENV_FILE" ]]; then
  COMPOSE_CMD+=(--env-file "$ENV_FILE")
fi
COMPOSE_CMD+=(-f "$COMPOSE_FILE")

echo "[info] building encrypted model package from $MODEL_FILE"
"${COMPOSE_CMD[@]}" exec -T backend sh -lc "\
  python -m app.services.model_package_tool \
    --model-path /app/app/uploads/open_models/mobilenet_ssd_bundle.zip \
    --model-id ${MODEL_ID} \
    --version ${VERSION} \
    --task-type ${TASK_TYPE} \
    --plugin-name ${PLUGIN_NAME} \
    --encrypt-key /app/keys/model_encrypt.key \
    --signing-private-key /app/keys/model_sign_private.pem \
    --publisher platform-model-store \
    --output $OUTPUT_ZIP"

echo "[ok] package ready: $ROOT_DIR/backend/app/uploads/${OUTPUT_NAME}"
