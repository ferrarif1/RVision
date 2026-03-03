import base64
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from io import BytesIO

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class ModelPackageError(Exception):
    pass


@dataclass
class ParsedModelPackage:
    manifest: dict
    manifest_bytes: bytes
    model_enc_bytes: bytes
    signature_bytes: bytes
    model_hash: str


REQUIRED_FILES = {"manifest.json", "model.enc", "signature.sig", "README.txt"}


def _load_public_key(public_key_path: str):
    if not os.path.exists(public_key_path):
        raise ModelPackageError(f"Public key not found: {public_key_path}")
    with open(public_key_path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def parse_and_validate_model_package(package_bytes: bytes, public_key_path: str) -> ParsedModelPackage:
    try:
        zip_buffer = BytesIO(package_bytes)
        with zipfile.ZipFile(zip_buffer) as zf:
            names = set(zf.namelist())
            missing = REQUIRED_FILES - names
            if missing:
                raise ModelPackageError(f"Missing required files: {sorted(missing)}")

            manifest_bytes = zf.read("manifest.json")
            model_enc_bytes = zf.read("model.enc")
            signature_bytes = zf.read("signature.sig")
    except zipfile.BadZipFile as exc:
        raise ModelPackageError("Invalid zip format") from exc

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelPackageError("Invalid manifest.json") from exc

    if "model_id" not in manifest or "version" not in manifest or "model_hash" not in manifest:
        raise ModelPackageError("manifest.json must contain model_id/version/model_hash")

    computed_hash = hashlib.sha256(model_enc_bytes).hexdigest()
    if manifest["model_hash"] != computed_hash:
        raise ModelPackageError("model_hash mismatch against model.enc")

    public_key = _load_public_key(public_key_path)
    payload = manifest_bytes + model_enc_bytes

    try:
        public_key.verify(signature_bytes, payload, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise ModelPackageError("signature verify failed") from exc

    return ParsedModelPackage(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        model_enc_bytes=model_enc_bytes,
        signature_bytes=signature_bytes,
        model_hash=computed_hash,
    )


def persist_model_package(model_repo_path: str, model_record_id: str, parsed: ParsedModelPackage) -> dict[str, str]:
    model_dir = os.path.join(model_repo_path, model_record_id)
    os.makedirs(model_dir, exist_ok=True)

    manifest_path = os.path.join(model_dir, "manifest.json")
    model_enc_path = os.path.join(model_dir, "model.enc")
    signature_path = os.path.join(model_dir, "signature.sig")

    with open(manifest_path, "wb") as f:
        f.write(parsed.manifest_bytes)
    with open(model_enc_path, "wb") as f:
        f.write(parsed.model_enc_bytes)
    with open(signature_path, "wb") as f:
        f.write(parsed.signature_bytes)

    return {
        "manifest_uri": manifest_path,
        "encrypted_uri": model_enc_path,
        "signature_uri": signature_path,
    }


def load_model_blobs(manifest_path: str, model_enc_path: str, signature_path: str) -> dict[str, str]:
    with open(manifest_path, "rb") as f:
        manifest_bytes = f.read()
    with open(model_enc_path, "rb") as f:
        model_enc_bytes = f.read()
    with open(signature_path, "rb") as f:
        signature_bytes = f.read()

    return {
        "manifest_b64": base64.b64encode(manifest_bytes).decode("utf-8"),
        "model_enc_b64": base64.b64encode(model_enc_bytes).decode("utf-8"),
        "signature_b64": base64.b64encode(signature_bytes).decode("utf-8"),
    }
