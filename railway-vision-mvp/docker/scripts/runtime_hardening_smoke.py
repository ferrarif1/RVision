#!/usr/bin/env python3
"""Runtime smoke checks for authentication and asset-upload hardening."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_DIR = ROOT / "docs" / "qa" / "reports"
API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")


class CheckFailure(RuntimeError):
    """Raised when a hardening check fails."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_request(method: str, path: str, payload: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = request.Request(url=f"{API_BASE}{path}", method=method, data=body, headers=headers)
    try:
        with request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return exc.code, parsed


def _multipart_body(fields: dict[str, str], file_name: str, file_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----vistralhardening{uuid.uuid4().hex}"
    parts: list[bytes] = []

    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")

    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8"))
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    return b"".join(parts), boundary


def _upload_request(
    token: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
    *,
    asset_purpose: str = "inference",
    dataset_label: str = "",
) -> tuple[int, dict]:
    body, boundary = _multipart_body(
        fields={
            "sensitivity_level": "L2",
            "asset_purpose": asset_purpose,
            "dataset_label": dataset_label,
            "use_case": "qa-hardening",
        },
        file_name=file_name,
        file_bytes=file_bytes,
        content_type=content_type,
    )
    req = request.Request(
        url=f"{API_BASE}/assets/upload",
        method="POST",
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return exc.code, parsed


def _dataset_zip_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("batch-a/frame-001.png", b"zip-frame-001")
        zf.writestr("batch-a/frame-002.jpg", b"zip-frame-002")
        zf.writestr("batch-b/nested/clip-003.mp4", b"zip-clip-003")
        zf.writestr("README.txt", b"dataset bundle")
    return buffer.getvalue()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_smoke(report_dir: Path) -> dict:
    report = {
        "status": "ok",
        "meta": {
            "generated_at": _now_iso(),
            "api_base": API_BASE,
        },
        "checks": {},
    }

    status_code, login_ok = _json_request("POST", "/auth/login", {"username": "buyer_operator", "password": "buyer123"})
    _assert(status_code == 200, "valid login failed")
    token = login_ok.get("access_token") or ""
    _assert(token, "valid login did not return access_token")
    report["checks"]["valid_login"] = {"status_code": status_code, "username": "buyer_operator"}

    status_code, invalid_login = _json_request("POST", "/auth/login", {"username": "buyer_operator", "password": "wrong-password"})
    _assert(status_code == 401, "invalid login was not rejected with 401")
    report["checks"]["invalid_login_rejected"] = {
        "status_code": status_code,
        "detail": invalid_login.get("detail"),
    }

    status_code, empty_upload = _upload_request(token, "empty.png", b"", "image/png")
    _assert(status_code == 400, "empty asset upload was not rejected with 400")
    _assert("Empty file" in str(empty_upload.get("detail") or ""), "empty upload rejection detail mismatch")
    report["checks"]["empty_upload_rejected"] = {
        "status_code": status_code,
        "detail": empty_upload.get("detail"),
    }

    duplicate_file_name = f"runtime-hardening-{uuid.uuid4().hex[:8]}.png"
    duplicate_bytes = b"runtime-hardening-payload"
    status_code, first_upload = _upload_request(token, duplicate_file_name, duplicate_bytes, "image/png")
    _assert(status_code == 200, "first upload for duplicate reuse check failed")
    status_code, second_upload = _upload_request(token, duplicate_file_name, duplicate_bytes, "image/png")
    _assert(status_code == 200, "second upload for duplicate reuse check failed")
    _assert(first_upload.get("id") == second_upload.get("id"), "duplicate upload did not reuse existing asset id")
    _assert(bool(second_upload.get("reused")) is True, "duplicate upload did not mark reused=true")
    report["checks"]["duplicate_upload_reused"] = {
        "status_code": status_code,
        "asset_id": second_upload.get("id"),
        "reused": second_upload.get("reused"),
    }

    status_code, zip_upload = _upload_request(
        token,
        f"dataset-{uuid.uuid4().hex[:8]}.zip",
        _dataset_zip_bytes(),
        "application/zip",
        asset_purpose="training",
        dataset_label="qa-zip-training",
    )
    _assert(status_code == 200, "zip dataset upload failed")
    _assert(zip_upload.get("asset_type") == "archive", "zip dataset was not classified as archive")
    archive_meta = zip_upload.get("meta") or {}
    _assert(int(archive_meta.get("archive_resource_count") or 0) == 3, "zip dataset resource count mismatch")
    _assert(int(archive_meta.get("archive_max_depth") or 0) >= 1, "zip dataset nested folder depth was not detected")
    report["checks"]["zip_dataset_upload"] = {
        "status_code": status_code,
        "asset_id": zip_upload.get("id"),
        "asset_type": zip_upload.get("asset_type"),
        "archive_resource_count": archive_meta.get("archive_resource_count"),
        "archive_max_depth": archive_meta.get("archive_max_depth"),
    }

    status_code, zip_inference_error = _upload_request(
        token,
        f"inference-{uuid.uuid4().hex[:8]}.zip",
        _dataset_zip_bytes(),
        "application/zip",
        asset_purpose="inference",
    )
    _assert(status_code == 400, "zip inference upload was not rejected with 400")
    _assert("ZIP dataset asset is only allowed" in str(zip_inference_error.get("detail") or ""), "zip inference rejection detail mismatch")
    report["checks"]["zip_inference_rejected"] = {
        "status_code": status_code,
        "detail": zip_inference_error.get("detail"),
    }

    status_code, type_error = _upload_request(token, "bad.txt", b"hardening", "text/plain")
    _assert(status_code == 400, "unsupported file type was not rejected with 400")
    _assert("Unsupported file type" in str(type_error.get("detail") or ""), "unsupported type rejection detail mismatch")
    report["checks"]["unsupported_type_rejected"] = {
        "status_code": status_code,
        "detail": type_error.get("detail"),
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _write_json(report_dir / f"runtime_hardening_smoke_{timestamp}.json", report)
    _write_json(report_dir / "runtime_hardening_latest.json", report)
    return report


def main() -> None:
    report_dir = DEFAULT_REPORT_DIR
    try:
        report = run_smoke(report_dir)
    except CheckFailure as exc:
        failure = {
            "status": "failed",
            "meta": {
                "generated_at": _now_iso(),
                "api_base": API_BASE,
            },
            "error": str(exc),
        }
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        _write_json(report_dir / "runtime_hardening_latest.json", failure)
        _write_json(report_dir / f"runtime_hardening_smoke_{timestamp}.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("[ok] runtime hardening smoke passed")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="rv-hardening-smoke-"):
        main()
