#!/usr/bin/env python3
"""API parity and release-gate regression checks for VisionHub."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


API_BASE = os.getenv("PARITY_API_BASE", "http://localhost:8000")
ROOT = Path(__file__).resolve().parents[2]

ROLE_CREDENTIALS = {
    "platform_admin": ("platform_admin", "platform123"),
    "platform_operator": ("platform_operator", "platform123"),
    "platform_auditor": ("platform_auditor", "platform123"),
    "supplier_engineer": ("supplier_demo", "supplier123"),
    "buyer_operator": ("buyer_operator", "buyer123"),
    "buyer_auditor": ("buyer_auditor", "buyer123"),
}

EXPECTED_PERMISSIONS = {
    "platform_admin": {
        "asset.upload",
        "audit.read",
        "dashboard.view",
        "data.l3.read",
        "device.read",
        "model.approve",
        "model.release",
        "model.submit",
        "model.view",
        "result.read",
        "settings.view",
        "task.create",
        "training.job.create",
        "training.job.view",
        "training.worker.manage",
    },
    "platform_operator": {
        "asset.upload",
        "dashboard.view",
        "device.read",
        "model.view",
        "result.read",
        "settings.view",
        "task.create",
        "training.job.create",
        "training.job.view",
    },
    "platform_auditor": {
        "audit.read",
        "dashboard.view",
        "data.l3.read",
        "device.read",
        "model.view",
        "result.read",
        "settings.view",
        "training.job.view",
    },
    "supplier_engineer": {
        "dashboard.view",
        "model.submit",
        "model.view",
        "settings.view",
        "training.job.view",
    },
    "buyer_operator": {
        "asset.upload",
        "dashboard.view",
        "device.read",
        "model.view",
        "result.read",
        "settings.view",
        "task.create",
    },
    "buyer_auditor": {
        "dashboard.view",
        "device.read",
        "model.view",
        "result.read",
        "settings.view",
    },
}

TASK_REQUIRED_FIELDS = {
    "id",
    "status",
    "task_type",
    "model_id",
    "asset_id",
    "device_code",
    "policy",
    "created_at",
    "started_at",
    "finished_at",
    "error_message",
    "result_count",
}

RESULT_REQUIRED_FIELDS = {
    "id",
    "task_id",
    "model_id",
    "model_hash",
    "alert_level",
    "result_json",
    "screenshot_uri",
    "duration_ms",
    "created_at",
}


class CheckFailure(RuntimeError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _json_request(method: str, path: str, token: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = request.Request(url=f"{API_BASE}{path}", method=method, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise CheckFailure(f"HTTP {exc.code} {method} {path}: {body}") from exc


def _multipart_body(file_field: str, file_name: str, file_bytes: bytes, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----rvparity{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")

    parts.append(f"--{boundary}\r\n".encode())
    parts.append(f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'.encode())
    parts.append(b"Content-Type: image/png\r\n\r\n")
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _upload_asset(token: str, file_bytes: bytes, file_name: str = "parity_asset.png") -> dict[str, Any]:
    body, boundary = _multipart_body(
        file_field="file",
        file_name=file_name,
        file_bytes=file_bytes,
        fields={"sensitivity_level": "L2", "source_uri": "parity://regression"},
    )
    req = request.Request(
        url=f"{API_BASE}/assets/upload",
        method="POST",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body_txt = exc.read().decode("utf-8", errors="replace")
        raise CheckFailure(f"HTTP {exc.code} POST /assets/upload: {body_txt}") from exc


def _login(username: str, password: str) -> dict[str, Any]:
    return _json_request("POST", "/auth/login", payload={"username": username, "password": password})


def _load_demo_asset_bytes() -> bytes:
    candidates = [
        ROOT / "demo_data" / "CAR123456_demo.png",
        ROOT / "demo_data" / "BOLT_MISSING_001.png",
    ]
    for c in candidates:
        if c.exists():
            return c.read_bytes()

    # Fallback tiny valid PNG.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAusB9Y9hW4kAAAAASUVORK5CYII="
    )
    import base64

    return base64.b64decode(tiny_png_b64)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def run_parity(allow_pending: bool, wait_seconds: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "ok",
        "meta": {
            "generated_at": _utc_now_iso(),
            "api_base": API_BASE,
            "allow_pending": allow_pending,
            "wait_seconds": wait_seconds,
        },
        "checks": {},
    }
    tokens: dict[str, str] = {}

    # 1) Role permission parity.
    role_details: dict[str, Any] = {}
    for role_name, (username, password) in ROLE_CREDENTIALS.items():
        login_data = _login(username, password)
        token = login_data["access_token"]
        tokens[role_name] = token
        perm_set = set(login_data.get("permissions") or [])
        expected = EXPECTED_PERMISSIONS[role_name]
        _assert(
            perm_set == expected,
            f"permissions mismatch for {role_name}: expected={sorted(expected)} actual={sorted(perm_set)}",
        )

        me = _json_request("GET", "/users/me", token=token)
        me_perm = set(me.get("permissions") or [])
        _assert(me_perm == expected, f"/users/me permissions mismatch for {role_name}")
        role_details[role_name] = {"username": username, "permissions": sorted(perm_set)}
    report["checks"]["role_permission_parity"] = role_details

    # 2) Audit endpoint access boundary.
    admin_audit = _json_request("GET", "/audit?limit=3", token=tokens["platform_admin"])
    _assert(isinstance(admin_audit, list), "admin audit response should be list")

    denied_ok = False
    try:
        _json_request("GET", "/audit?limit=1", token=tokens["buyer_operator"])
    except CheckFailure as exc:
        denied_ok = "HTTP 403" in str(exc)
    _assert(denied_ok, "buyer_operator should be denied from audit endpoint")
    report["checks"]["audit_access_boundary"] = {"admin_list_ok": True, "buyer_denied_ok": True}

    # 3) Task/results contract parity.
    buyer_token = tokens["buyer_operator"]
    models = _json_request("GET", "/models", token=buyer_token)
    _assert(isinstance(models, list) and len(models) > 0, "buyer has no visible released models")
    chosen_model = models[0]
    model_id = chosen_model["id"]
    task_type = (
        chosen_model["model_code"]
        if chosen_model["model_code"] in {"object_detect", "car_number_ocr", "bolt_missing_detect"}
        else "car_number_ocr"
    )

    asset = _upload_asset(buyer_token, _load_demo_asset_bytes(), file_name=f"parity_{task_type}.png")
    asset_id = asset["id"]

    task = _json_request(
        "POST",
        "/tasks/create",
        token=buyer_token,
        payload={
            "model_id": model_id,
            "asset_id": asset_id,
            "task_type": task_type,
            "device_code": "edge-01",
            "policy": {
                "upload_raw_video": False,
                "upload_frames": True,
                "desensitize_frames": False,
                "retention_days": 7,
                "quick_detect": {"object_prompt": "car"} if task_type == "object_detect" else {},
                "force_mock_object_detector": task_type == "object_detect",
                "force_mock_ocr": True,
                "force_fallback_detector": True,
            },
        },
    )
    task_id = task["id"]
    _assert(task["status"] == "PENDING", "new task should start with PENDING")

    # Poll task status.
    latest_task = None
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        latest_task = _json_request("GET", f"/tasks/{task_id}", token=buyer_token)
        status = latest_task["status"]
        if status in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(3)

    _assert(latest_task is not None, "task query failed during polling")
    status = latest_task["status"]
    if status not in {"SUCCEEDED", "FAILED"} and not allow_pending:
        raise CheckFailure(f"task did not reach terminal status in {wait_seconds}s: {status}")

    task_keys = set(latest_task.keys())
    _assert(TASK_REQUIRED_FIELDS.issubset(task_keys), f"task response missing fields: {sorted(TASK_REQUIRED_FIELDS - task_keys)}")

    results = _json_request("GET", f"/results?task_id={task_id}", token=buyer_token)
    _assert(isinstance(results, list), "results should be list")
    if results:
        result_keys = set(results[0].keys())
        _assert(
            RESULT_REQUIRED_FIELDS.issubset(result_keys),
            f"result response missing fields: {sorted(RESULT_REQUIRED_FIELDS - result_keys)}",
        )

    exported = _json_request("GET", f"/results/export?task_id={task_id}", token=buyer_token)
    _assert("count" in exported and "items" in exported, "export response missing keys")
    _assert(exported["task_id"] == task_id, "export task_id mismatch")

    # 4) Audit trace for result export exists.
    audit_rows = _json_request("GET", "/audit?action=RESULT_EXPORT&limit=200", token=tokens["platform_admin"])
    has_export_audit = any(str(row.get("resource_id")) == task_id for row in audit_rows)
    _assert(has_export_audit, "RESULT_EXPORT audit for parity task not found")

    report["checks"]["task_result_contract_parity"] = {
        "task_id": task_id,
        "task_status": status,
        "result_count": len(results),
        "export_count": exported["count"],
    }
    report["checks"]["audit_trace_parity"] = {
        "result_export_audit_found": True,
        "audit_rows_checked": len(audit_rows),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run API parity regression checks")
    parser.add_argument("--allow-pending", action="store_true", help="allow non-terminal task status")
    parser.add_argument("--wait-seconds", type=int, default=90, help="task wait timeout")
    parser.add_argument("--output", type=str, default="", help="optional JSON output file path")
    args = parser.parse_args()

    report = run_parity(allow_pending=args.allow_pending, wait_seconds=args.wait_seconds)
    if args.output:
        _write_json(Path(args.output), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except CheckFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
