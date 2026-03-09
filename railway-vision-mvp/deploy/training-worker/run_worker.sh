#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/worker.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/worker.env"
  set +a
fi

if [[ -z "${TRAINING_BACKEND_ROOT:-}" ]]; then
  if [[ -d "$ROOT/backend" ]]; then
    export TRAINING_BACKEND_ROOT="$ROOT/backend"
  elif [[ -d "$ROOT/../../backend" ]]; then
    export TRAINING_BACKEND_ROOT="$ROOT/../../backend"
  fi
fi

if [[ -z "${MODEL_DECRYPT_KEY:-}" ]]; then
  if [[ -f "$ROOT/keys/model_decrypt.key" ]]; then
    export MODEL_DECRYPT_KEY="$ROOT/keys/model_decrypt.key"
  elif [[ -f "$ROOT/../../edge/keys/model_decrypt.key" ]]; then
    export MODEL_DECRYPT_KEY="$ROOT/../../edge/keys/model_decrypt.key"
  fi
fi

if [[ -z "${MODEL_ENCRYPT_KEY:-}" ]]; then
  if [[ -f "$ROOT/keys/model_encrypt.key" ]]; then
    export MODEL_ENCRYPT_KEY="$ROOT/keys/model_encrypt.key"
  elif [[ -f "$ROOT/../../docker/keys/model_encrypt.key" ]]; then
    export MODEL_ENCRYPT_KEY="$ROOT/../../docker/keys/model_encrypt.key"
  fi
fi

if [[ -z "${MODEL_SIGN_PRIVATE_KEY:-}" ]]; then
  if [[ -f "$ROOT/keys/model_sign_private.pem" ]]; then
    export MODEL_SIGN_PRIVATE_KEY="$ROOT/keys/model_sign_private.pem"
  elif [[ -f "$ROOT/../../docker/keys/model_sign_private.pem" ]]; then
    export MODEL_SIGN_PRIVATE_KEY="$ROOT/../../docker/keys/model_sign_private.pem"
  fi
fi

WORKER_SCRIPT="$ROOT/training_worker_runner.py"
if [[ ! -f "$WORKER_SCRIPT" ]]; then
  WORKER_SCRIPT="$ROOT/../../docker/scripts/training_worker_runner.py"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
exec "$PYTHON_BIN" "$WORKER_SCRIPT" "$@"
