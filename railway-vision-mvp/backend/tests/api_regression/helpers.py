from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx

API_BASE_ENV = "VISTRAL_API_BASE"
DEFAULT_API_BASE = "http://localhost:8000"
EDGE_DEVICE_CODE = "edge-01"
EDGE_TOKEN = "EDGE_TOKEN_CHANGE_ME"
EDGE_AGENT_VERSION = "vistral-api-regression/2026.03"
REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_SIGN_PRIVATE_KEY = REPO_ROOT / "docker" / "keys" / "model_sign_private.pem"


class ApiRegressionHelper(unittest.TestCase):
    client: httpx.Client
    api_base: str
    buyer_token: str
    platform_token: str
    supplier_token: str

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.api_base = os.getenv(API_BASE_ENV, DEFAULT_API_BASE).rstrip("/")
        cls.client = httpx.Client(
            base_url=cls.api_base,
            timeout=60.0,
            verify=False,
            follow_redirects=True,
            trust_env=False,
        )
        health = cls.client.get("/health")
        if health.status_code != 200:
            raise RuntimeError(f"backend health check failed: {health.status_code} {health.text}")
        cls.buyer_token = cls.login("buyer_operator", "buyer123")
        cls.platform_token = cls.login("platform_admin", "platform123")
        cls.supplier_token = cls.login("supplier_demo", "supplier123")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        super().tearDownClass()

    @classmethod
    def login(cls, username: str, password: str) -> str:
        response = cls.client.post("/auth/login", json={"username": username, "password": password})
        if response.status_code != 200:
            raise RuntimeError(f"login failed for {username}: {response.status_code} {response.text}")
        return response.json()["access_token"]

    @staticmethod
    def unique_name(prefix: str, suffix: str = "") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:10]}{suffix}"

    @classmethod
    def auth_headers(cls, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @classmethod
    def edge_headers(cls) -> dict[str, str]:
        return {
            "X-Edge-Device-Code": EDGE_DEVICE_CODE,
            "X-Edge-Token": EDGE_TOKEN,
            "X-Edge-Agent-Version": EDGE_AGENT_VERSION,
        }

    @classmethod
    def worker_headers(cls, worker_code: str, worker_token: str) -> dict[str, str]:
        return {
            "X-Training-Worker-Code": worker_code,
            "X-Training-Worker-Token": worker_token,
        }

    def request_json(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        expected_status: int = 200,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        merged_headers = dict(headers or {})
        if token:
            merged_headers.update(self.auth_headers(token))
        response = self.client.request(method, path, headers=merged_headers, **kwargs)
        self.assertEqual(
            response.status_code,
            expected_status,
            msg=f"{method} {path} expected {expected_status}, got {response.status_code}: {response.text}",
        )
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response

    def upload_asset(
        self,
        *,
        token: str,
        filename: str,
        content: bytes,
        asset_purpose: str,
        use_case: str,
        intended_model_code: str,
        dataset_label: str = "",
        sensitivity_level: str = "L2",
    ) -> dict[str, Any]:
        files = {"file": (filename, io.BytesIO(content), "application/octet-stream")}
        data = {
            "sensitivity_level": sensitivity_level,
            "asset_purpose": asset_purpose,
            "dataset_label": dataset_label,
            "use_case": use_case,
            "intended_model_code": intended_model_code,
        }
        return self.request_json("POST", "/assets/upload", token=token, files=files, data=data)

    @staticmethod
    def fake_image_bytes(label: str) -> bytes:
        return f"Vistral regression image:{label}".encode("utf-8")

    @staticmethod
    def tiny_png_bytes() -> bytes:
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sX6ixsAAAAASUVORK5CYII="
        )

    @staticmethod
    def screenshot_b64(label: str) -> str:
        return base64.b64encode(ApiRegressionHelper.fake_image_bytes(label)).decode("utf-8")

    @staticmethod
    def nested_dataset_zip(label: str, media_count: int = 2) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for index in range(media_count):
                zf.writestr(f"images/batch_{index + 1}/{label}_{index + 1}.jpg", f"dataset-image-{label}-{index + 1}".encode("utf-8"))
            zf.writestr("notes/readme.txt", b"ignored metadata")
        return buffer.getvalue()

    def buyer_models(self) -> list[dict[str, Any]]:
        rows = self.request_json("GET", "/models", token=self.buyer_token)
        self.assertIsInstance(rows, list)
        self.assertTrue(rows, "buyer-visible model list is empty; run bootstrap_demo.sh first")
        return rows

    @staticmethod
    def model_package_bytes(
        *,
        model_code: str,
        version: str,
        model_type: str = "expert",
        runtime: str = "python",
        plugin_name: str = "car_number_ocr",
        task_type: str = "car_number_ocr",
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> bytes:
        if not MODEL_SIGN_PRIVATE_KEY.exists():
            raise RuntimeError(f"model signing private key not found: {MODEL_SIGN_PRIVATE_KEY}")
        if not shutil_which("openssl"):
            raise RuntimeError("openssl is required for api regression model package signing")

        normalized_inputs = inputs or {"media": ["image"]}
        normalized_outputs = outputs or {"predictions": ["label", "score", "bbox", "text"]}
        model_enc_bytes = f"candidate::{model_code}::{version}::{uuid.uuid4().hex}".encode("utf-8")
        model_hash = hashlib.sha256(model_enc_bytes).hexdigest()
        manifest = {
            "schema_version": "1.0",
            "model_id": model_code,
            "version": version,
            "model_hash": model_hash,
            "model_type": model_type,
            "runtime": runtime,
            "task_type": task_type,
            "plugin_name": plugin_name,
            "inputs": normalized_inputs,
            "outputs": normalized_outputs,
            "input_schema": normalized_inputs,
            "output_schema": normalized_outputs,
            "model_format": "bin",
            "model_file_name": f"{model_code}.bin",
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")

        with tempfile.TemporaryDirectory(prefix="vistral-api-model-") as tmpdir:
            tmp = Path(tmpdir)
            payload_path = tmp / "payload.bin"
            signature_path = tmp / "signature.sig"
            payload_path.write_bytes(manifest_bytes + model_enc_bytes)
            subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", str(MODEL_SIGN_PRIVATE_KEY), "-out", str(signature_path), str(payload_path)],
                check=True,
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )
            signature_bytes = signature_path.read_bytes()

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr("model.enc", model_enc_bytes)
            zf.writestr("signature.sig", signature_bytes)
            zf.writestr(
                "README.txt",
                "Vistral regression model package\n"
                "- manifest.json\n"
                "- model.enc\n"
                "- signature.sig\n",
            )
        return buffer.getvalue()

    def schedulable_model(self, *, asset_id: str, task_type: str | None, intent_text: str) -> dict[str, Any]:
        decision = self.request_json(
            "POST",
            "/tasks/recommend-model",
            token=self.buyer_token,
            json={
                "asset_id": asset_id,
                "task_type": task_type,
                "device_code": EDGE_DEVICE_CODE,
                "intent_text": intent_text,
                "limit": 3,
            },
        )
        selected_model = decision.get("selected_model")
        self.assertIsNotNone(selected_model, f"no schedulable model found: {decision}")
        return decision


def shutil_which(command: str) -> str | None:
    for base in os.getenv("PATH", "").split(os.pathsep):
        candidate = Path(base) / command
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
