#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$DOCKER_DIR/.." && pwd)"

CERT_DIR="$DOCKER_DIR/certs"
KEY_DIR="$DOCKER_DIR/keys"
EDGE_KEY_DIR="$ROOT_DIR/edge/keys"

mkdir -p "$CERT_DIR" "$KEY_DIR" "$EDGE_KEY_DIR"

if [[ ! -f "$CERT_DIR/server.key" || ! -f "$CERT_DIR/server.crt" ]]; then
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -subj "/C=CN/ST=BJ/L=BJ/O=Railway/CN=railway-vision.local"
fi

if [[ ! -f "$KEY_DIR/model_sign_private.pem" || ! -f "$KEY_DIR/model_sign_public.pem" ]]; then
  openssl genrsa -out "$KEY_DIR/model_sign_private.pem" 2048
  openssl rsa -in "$KEY_DIR/model_sign_private.pem" -pubout -out "$KEY_DIR/model_sign_public.pem"
fi

if [[ ! -f "$KEY_DIR/model_encrypt.key" ]]; then
  KEY_PATH="$KEY_DIR/model_encrypt.key" python3 - <<'PY'
import base64
import os
key = base64.urlsafe_b64encode(os.urandom(32))
with open(os.environ["KEY_PATH"], "wb") as f:
    f.write(key)
PY
fi

cp "$KEY_DIR/model_encrypt.key" "$EDGE_KEY_DIR/model_decrypt.key"
cp "$KEY_DIR/model_sign_public.pem" "$EDGE_KEY_DIR/model_sign_public.pem"
chmod 600 "$CERT_DIR/server.key" "$KEY_DIR/model_sign_private.pem" "$KEY_DIR/model_encrypt.key" "$EDGE_KEY_DIR/model_decrypt.key"

echo "Local certs/keys are ready."
echo "- TLS cert: $CERT_DIR/server.crt"
echo "- Signing private key: $KEY_DIR/model_sign_private.pem"
echo "- Signing public key:  $KEY_DIR/model_sign_public.pem"
echo "- Model encryption key: $KEY_DIR/model_encrypt.key"
