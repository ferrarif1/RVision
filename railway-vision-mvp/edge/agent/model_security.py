import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from agent.config import settings


@dataclass
class LocalModelArtifacts:
    model_id: str
    model_hash: str
    manifest: dict
    encrypted_path: str
    decrypted_path: str


class ModelSecurityError(Exception):
    pass


def _load_public_key(path: str):
    if not os.path.exists(path):
        raise ModelSecurityError(f"missing edge public key: {path}")
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def verify_and_decrypt_model(model_payload: dict, cache_models_dir: str, edge_public_key_path: str) -> LocalModelArtifacts:
    model_id = model_payload["model_id"]
    manifest_bytes = base64.b64decode(model_payload["manifest_b64"])
    model_enc_bytes = base64.b64decode(model_payload["model_enc_b64"])
    signature_bytes = base64.b64decode(model_payload["signature_b64"])

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    computed_hash = hashlib.sha256(model_enc_bytes).hexdigest()
    if computed_hash != manifest.get("model_hash") or computed_hash != model_payload.get("model_hash"):
        raise ModelSecurityError("model hash mismatch")

    public_key = _load_public_key(edge_public_key_path)
    try:
        public_key.verify(signature_bytes, manifest_bytes + model_enc_bytes, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise ModelSecurityError("model signature verify failed") from exc

    if not os.path.exists(settings.edge_decrypt_key_path):
        raise ModelSecurityError(f"missing decrypt key: {settings.edge_decrypt_key_path}")

    with open(settings.edge_decrypt_key_path, "rb") as f:
        decrypt_key = f.read().strip()

    try:
        decrypted_bytes = Fernet(decrypt_key).decrypt(model_enc_bytes)
    except Exception as exc:
        raise ModelSecurityError("model decrypt failed") from exc

    model_dir = os.path.join(cache_models_dir, model_id)
    os.makedirs(model_dir, exist_ok=True)

    encrypted_path = os.path.join(model_dir, "model.enc")
    model_file_name = str(manifest.get("model_file_name") or "model.dec")
    ext = Path(model_file_name).suffix
    # Keep expected framework extension (.pt/.onnx/...) to allow runtime loaders to detect backend.
    if not ext or len(ext) > 10:
        ext = ".dec"
    decrypted_path = os.path.join(model_dir, f"model{ext}")
    manifest_path = os.path.join(model_dir, "manifest.json")
    signature_path = os.path.join(model_dir, "signature.sig")

    with open(encrypted_path, "wb") as f:
        f.write(model_enc_bytes)
    with open(decrypted_path, "wb") as f:
        f.write(decrypted_bytes)
    with open(manifest_path, "wb") as f:
        f.write(manifest_bytes)
    with open(signature_path, "wb") as f:
        f.write(signature_bytes)

    return LocalModelArtifacts(
        model_id=model_id,
        model_hash=computed_hash,
        manifest=manifest,
        encrypted_path=encrypted_path,
        decrypted_path=decrypted_path,
    )
