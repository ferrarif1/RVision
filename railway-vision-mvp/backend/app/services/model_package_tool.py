"""Utility to build the platform model package format.

Usage:
python -m app.services.model_package_tool \
  --model-path /path/to/model.onnx \
  --model-id car_number_ocr \
  --version v1.0.0 \
  --encrypt-key /app/keys/model_encrypt.key \
  --signing-private-key /app/keys/model_sign_private.pem \
  --output /tmp/model_package.zip
"""

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _load_schema_arg(raw: str, fallback: dict) -> dict:
    text = str(raw or "").strip()
    if not text:
        return fallback
    if text.startswith("{"):
        return json.loads(text)
    return {"schema": text}


def build_package(
    model_path: Path,
    model_id: str,
    version: str,
    encrypt_key_path: Path,
    signing_private_key_path: Path,
    output_path: Path,
    task_type: str,
    input_schema: str,
    output_schema: str,
    publisher: str,
    model_type: str,
    runtime: str,
    plugin_name: str,
) -> None:
    model_bytes = model_path.read_bytes()
    encrypt_key = encrypt_key_path.read_bytes().strip()
    encrypted_model_bytes = Fernet(encrypt_key).encrypt(model_bytes)
    model_hash = hashlib.sha256(encrypted_model_bytes).hexdigest()

    manifest = {
        "schema_version": "1.0",
        "model_id": model_id,
        "version": version,
        "model_hash": model_hash,
        "model_file_name": model_path.name,
        "model_format": model_path.suffix.lstrip(".").lower() or "bin",
        "task_type": task_type,
        "model_type": model_type,
        "runtime": runtime,
        "plugin_name": plugin_name,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "inputs": _load_schema_arg(input_schema, {"media": ["image", "frames"]}),
        "outputs": _load_schema_arg(
            output_schema,
            {"predictions": ["label", "score", "bbox", "mask", "text", "attributes"], "metrics": ["duration_ms"]},
        ),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "publisher": publisher,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")

    private_key = serialization.load_pem_private_key(signing_private_key_path.read_bytes(), password=None)
    signature = private_key.sign(manifest_bytes + encrypted_model_bytes, padding.PKCS1v15(), hashes.SHA256())

    readme_text = (
        "VisionHub model package\n"
        "- manifest.json: model metadata and hash\n"
        "- model.enc: encrypted model bytes\n"
        "- signature.sig: RSA signature for manifest+model.enc\n"
    )

    with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("model.enc", encrypted_model_bytes)
        zf.writestr("signature.sig", signature)
        zf.writestr("README.txt", readme_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build encrypted model package zip")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--encrypt-key", required=True)
    parser.add_argument("--signing-private-key", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--task-type", default="car_number_ocr")
    parser.add_argument("--input-schema", default="image|video")
    parser.add_argument("--output-schema", default="json:bbox,text,confidence")
    parser.add_argument("--publisher", default="railway-platform")
    parser.add_argument("--model-type", default="expert")
    parser.add_argument("--runtime", default="python")
    parser.add_argument("--plugin-name", default="")
    args = parser.parse_args()

    build_package(
        model_path=Path(args.model_path),
        model_id=args.model_id,
        version=args.version,
        encrypt_key_path=Path(args.encrypt_key),
        signing_private_key_path=Path(args.signing_private_key),
        output_path=Path(args.output),
        task_type=args.task_type,
        input_schema=args.input_schema,
        output_schema=args.output_schema,
        publisher=args.publisher,
        model_type=args.model_type,
        runtime=args.runtime,
        plugin_name=args.plugin_name or args.task_type or args.model_id,
    )
    print(f"Package generated: {args.output}")


if __name__ == "__main__":
    main()
