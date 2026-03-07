#!/usr/bin/env python3
"""Runtime smoke checks for the training control plane."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[2]
API_BASE = os.getenv("TRAINING_SMOKE_API_BASE", "http://localhost:8000")
PRIVATE_KEY_PATH = ROOT / "docker" / "keys" / "model_sign_private.pem"


class CheckFailure(RuntimeError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _json_request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 45,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)

    req = request.Request(url=f"{API_BASE}{path}", method=method, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise CheckFailure(f"HTTP {exc.code} {method} {path}: {body}") from exc


def _multipart_body(
    *,
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str,
    fields: dict[str, str],
) -> tuple[bytes, str]:
    boundary = f"----vistraltrain{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")

    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'.encode("utf-8"))
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _multipart_request(
    method: str,
    path: str,
    *,
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str,
    fields: dict[str, str],
    token: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    body, boundary = _multipart_body(
        file_field=file_field,
        file_name=file_name,
        file_bytes=file_bytes,
        content_type=content_type,
        fields=fields,
    )
    headers = {
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)

    req = request.Request(url=f"{API_BASE}{path}", method=method, data=body, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body_txt = exc.read().decode("utf-8", errors="replace")
        raise CheckFailure(f"HTTP {exc.code} {method} {path}: {body_txt}") from exc


def _login(username: str, password: str) -> dict[str, Any]:
    return _json_request("POST", "/auth/login", payload={"username": username, "password": password})


def _tiny_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAusB9Y9hW4kAAAAASUVORK5CYII="
    )


def _dataset_zip_bytes(prefix: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{prefix}/images/frame-001.png", _tiny_png_bytes())
        zf.writestr(f"{prefix}/images/frame-002.jpg", b"train-jpg-placeholder")
        zf.writestr(f"{prefix}/clips/clip-003.mp4", b"train-mp4-placeholder")
        zf.writestr(f"{prefix}/README.txt", b"dataset bundle")
    return buffer.getvalue()


def _upload_asset(token: str, purpose: str, file_name: str, file_bytes: bytes | None = None, content_type: str | None = None) -> dict[str, Any]:
    return _multipart_request(
        "POST",
        "/assets/upload",
        token=token,
        file_field="file",
        file_name=file_name,
        file_bytes=file_bytes if file_bytes is not None else _tiny_png_bytes(),
        content_type=content_type or "image/png",
        fields={
            "sensitivity_level": "L2",
            "asset_purpose": purpose,
            "dataset_label": f"qa-{purpose}",
            "use_case": "training-control-plane-smoke",
            "source_uri": "qa://training-smoke",
        },
    )


def _pick_base_model(models: list[dict[str, Any]]) -> dict[str, Any]:
    expert_owned = [row for row in models if row.get("model_type") == "expert" and row.get("owner_tenant_id")]
    expert_any = [row for row in models if row.get("model_type") == "expert"]
    if expert_owned:
        return expert_owned[0]
    if expert_any:
        return expert_any[0]
    if models:
        return models[0]
    raise CheckFailure("no models available for training smoke")


def _worker_headers(worker_code: str, worker_token: str) -> dict[str, str]:
    return {
        "X-Training-Worker-Code": worker_code,
        "X-Training-Worker-Token": worker_token,
    }


def _create_model_package(
    *,
    model_code: str,
    version: str,
    model_type: str,
    runtime: str,
    plugin_name: str,
    task_type: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
) -> bytes:
    if shutil.which("openssl") is None:
        raise CheckFailure("openssl is required for training smoke package signing")
    if not PRIVATE_KEY_PATH.exists():
        raise CheckFailure(f"model signing private key not found: {PRIVATE_KEY_PATH}")

    model_enc_bytes = f"candidate::{model_code}::{version}::{uuid.uuid4().hex}".encode("utf-8")
    model_hash = hashlib.sha256(model_enc_bytes).hexdigest()
    manifest = {
        "model_id": model_code,
        "version": version,
        "model_hash": model_hash,
        "model_type": model_type,
        "runtime": runtime,
        "task_type": task_type,
        "plugin_name": plugin_name,
        "inputs": inputs,
        "outputs": outputs,
        "input_schema": inputs,
        "output_schema": outputs,
        "model_format": "bin",
        "model_file_name": f"{model_code}.bin",
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")

    with tempfile.TemporaryDirectory(prefix="rv-train-smoke-") as tmpdir:
        tmp = Path(tmpdir)
        payload_path = tmp / "payload.bin"
        signature_path = tmp / "signature.sig"
        payload_path.write_bytes(manifest_bytes + model_enc_bytes)
        subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(PRIVATE_KEY_PATH), "-out", str(signature_path), str(payload_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        signature_bytes = signature_path.read_bytes()

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("model.enc", model_enc_bytes)
        zf.writestr("signature.sig", signature_bytes)
        zf.writestr("README.txt", "QA smoke generated candidate package.\n")
    return buffer.getvalue()


def _query_audit(token: str, action: str, *, resource_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    params = {"action": action, "limit": str(limit)}
    if resource_id:
        params["resource_id"] = resource_id
    return _json_request("GET", f"/audit?{parse.urlencode(params)}", token=token)


def run_smoke(report_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "ok",
        "meta": {
            "generated_at": _utc_now_iso(),
            "api_base": API_BASE,
        },
        "checks": {},
    }

    admin = _login("platform_admin", "platform123")
    buyer = _login("buyer_operator", "buyer123")
    admin_token = admin["access_token"]
    buyer_token = buyer["access_token"]

    buyer_models = _json_request("GET", "/models", token=buyer_token)
    base_model = _pick_base_model(buyer_models)

    train_asset = _upload_asset(
        buyer_token,
        "training",
        f"train_bundle_{uuid.uuid4().hex[:8]}.zip",
        file_bytes=_dataset_zip_bytes("train-bundle"),
        content_type="application/zip",
    )
    validation_asset = _upload_asset(
        buyer_token,
        "validation",
        f"validation_bundle_{uuid.uuid4().hex[:8]}.zip",
        file_bytes=_dataset_zip_bytes("validation-bundle"),
        content_type="application/zip",
    )
    report["checks"]["assets"] = {
        "training_asset_id": train_asset["id"],
        "validation_asset_id": validation_asset["id"],
        "training_asset_type": train_asset["asset_type"],
        "validation_asset_type": validation_asset["asset_type"],
        "training_resource_count": (train_asset.get("meta") or {}).get("archive_resource_count"),
        "validation_resource_count": (validation_asset.get("meta") or {}).get("archive_resource_count"),
    }

    worker_code = f"qa-train-worker-{uuid.uuid4().hex[:8]}"
    worker = _json_request(
        "POST",
        "/training/workers/register",
        token=admin_token,
        payload={
            "worker_code": worker_code,
            "name": "QA Training Worker",
            "host": "qa-smoke.local",
            "status": "ACTIVE",
            "labels": {"queue": "qa", "purpose": "smoke"},
            "resources": {"gpu_mem_mb": 8192, "gpu_count": 1},
        },
    )
    worker_token = worker["bootstrap_token"]
    worker_headers = _worker_headers(worker_code, worker_token)
    buyer_visible_workers = _json_request("GET", "/training/workers", token=buyer_token)
    _assert(any(row["worker_code"] == worker_code for row in buyer_visible_workers), "buyer cannot view registered training worker")

    target_model_code = f"qa_candidate_{uuid.uuid4().hex[:8]}"
    target_version = f"v1.{int(time.time())}"
    job = _json_request(
        "POST",
        "/training/jobs",
        token=buyer_token,
        payload={
            "asset_ids": [train_asset["id"]],
            "validation_asset_ids": [validation_asset["id"]],
            "base_model_id": base_model["id"],
            "training_kind": "finetune",
            "target_model_code": target_model_code,
            "target_version": target_version,
            "worker_selector": {"hosts": ["qa-smoke.local"], "labels": {"queue": "qa"}},
            "spec": {"epochs": 2, "batch_size": 4, "note": "qa smoke"},
        },
    )
    job_id = job["id"]
    buyer_job = _json_request("GET", f"/training/jobs/{job_id}", token=buyer_token)
    _assert(buyer_job["id"] == job_id, "buyer cannot read own training job")

    heartbeat = _json_request(
        "POST",
        "/training/workers/heartbeat",
        payload={"host": "qa-smoke.local", "status": "ACTIVE", "labels": {"queue": "qa"}, "resources": {"gpu_mem_mb": 8192}},
        extra_headers=worker_headers,
    )
    _assert(heartbeat["worker_code"] == worker_code, "worker heartbeat returned unexpected worker code")

    pull_jobs = _json_request(
        "POST",
        "/training/workers/pull-jobs",
        payload={"limit": 2},
        extra_headers=worker_headers,
    )
    assigned = next((row for row in pull_jobs["jobs"] if row["id"] == job_id), None)
    _assert(assigned is not None, "training job was not assigned to QA worker")

    train_asset_blob = _json_request(
        "GET",
        f"/training/workers/pull-asset?{parse.urlencode({'job_id': job_id, 'asset_id': train_asset['id']})}",
        extra_headers=worker_headers,
    )
    validation_asset_blob = _json_request(
        "GET",
        f"/training/workers/pull-asset?{parse.urlencode({'job_id': job_id, 'asset_id': validation_asset['id']})}",
        extra_headers=worker_headers,
    )
    _assert(train_asset_blob["asset"]["id"] == train_asset["id"], "training asset pull returned wrong asset")
    _assert(train_asset_blob["asset"]["asset_type"] == "archive", "training bundle asset type mismatch")
    _assert(int((train_asset_blob["asset"]["meta"] or {}).get("archive_resource_count") or 0) == 3, "training bundle resource count mismatch")
    _assert(validation_asset_blob["asset"]["purpose"] == "validation", "validation asset purpose mismatch")
    _assert(validation_asset_blob["asset"]["asset_type"] == "archive", "validation bundle asset type mismatch")

    base_model_blob = _json_request(
        "POST",
        "/training/workers/pull-base-model",
        payload={"job_id": job_id},
        extra_headers=worker_headers,
    )
    _assert(base_model_blob["base_model"]["id"] == base_model["id"], "base model pull returned wrong model")

    running = _json_request(
        "POST",
        "/training/workers/push-update",
        payload={"job_id": job_id, "status": "RUNNING", "output_summary": {"epoch": 1, "train_loss": 0.17}},
        extra_headers=worker_headers,
    )
    _assert(running["status"] == "RUNNING", "training job did not enter RUNNING")

    package_bytes = _create_model_package(
        model_code=target_model_code,
        version=target_version,
        model_type=base_model.get("model_type") or "expert",
        runtime=base_model.get("runtime") or "python",
        plugin_name=base_model.get("plugin_name") or target_model_code,
        task_type=base_model.get("task_type") or target_model_code,
        inputs=base_model.get("inputs") or {"media": ["image"], "context": [], "options": []},
        outputs=base_model.get("outputs") or {"predictions": ["label", "score"]},
    )

    candidate = _multipart_request(
        "POST",
        "/training/workers/upload-candidate",
        file_field="package",
        file_name=f"{target_model_code}.zip",
        file_bytes=package_bytes,
        content_type="application/zip",
        extra_headers=worker_headers,
        fields={
            "job_id": job_id,
            "training_round": "qa-round-1",
            "dataset_label": "qa-training-smoke",
            "training_summary": "candidate uploaded by QA smoke",
            "model_type": base_model.get("model_type") or "expert",
            "runtime": base_model.get("runtime") or "python",
            "plugin_name": base_model.get("plugin_name") or target_model_code,
            "inputs_json": json.dumps(base_model.get("inputs") or {"media": ["image"]}, ensure_ascii=False),
            "outputs_json": json.dumps(base_model.get("outputs") or {"predictions": ["label", "score"]}, ensure_ascii=False),
            "gpu_mem_mb": "1024",
            "latency_ms": "88",
        },
    )
    candidate_model = candidate["candidate_model"]

    finished = _json_request(
        "POST",
        "/training/workers/push-update",
        payload={"job_id": job_id, "status": "SUCCEEDED", "output_summary": {"epoch": 2, "final_loss": 0.03, "candidate_ready": True}},
        extra_headers=worker_headers,
    )
    _assert(finished["status"] == "SUCCEEDED", "training job did not enter SUCCEEDED")

    final_job = _json_request("GET", f"/training/jobs/{job_id}", token=admin_token)
    _assert(final_job["candidate_model"]["id"] == candidate_model["id"], "candidate model not linked on training job")
    _assert(final_job["output_summary"]["candidate_model_id"] == candidate_model["id"], "candidate model summary missing from training job output")
    _assert(final_job["output_summary"]["final_loss"] == 0.03, "final training metrics missing from training job output")

    candidate_in_registry = next((row for row in _json_request("GET", "/models", token=admin_token) if row["id"] == candidate_model["id"]), None)
    _assert(candidate_in_registry is not None, "candidate model missing from model registry")
    _assert(candidate_in_registry["status"] == "SUBMITTED", "candidate model should stay SUBMITTED before approval")

    empty_job = _json_request(
        "POST",
        "/training/jobs",
        token=buyer_token,
        payload={
            "asset_ids": [],
            "validation_asset_ids": [],
            "base_model_id": base_model["id"],
            "training_kind": "evaluate",
            "target_model_code": f"qa_empty_{uuid.uuid4().hex[:8]}",
            "target_version": f"v0.{int(time.time())}",
            "worker_selector": {"hosts": ["qa-smoke.local"]},
            "spec": {"note": "empty asset list support smoke"},
        },
    )
    _assert(empty_job["asset_count"] == 0, "empty training job did not keep asset_count=0")
    _assert(empty_job["validation_asset_count"] == 0, "empty training job did not keep validation_asset_count=0")

    control_job = _json_request(
        "POST",
        "/training/jobs",
        token=buyer_token,
        payload={
            "asset_ids": [train_asset["id"]],
            "validation_asset_ids": [],
            "base_model_id": base_model["id"],
            "training_kind": "finetune",
            "target_model_code": f"qa_control_{uuid.uuid4().hex[:8]}",
            "target_version": f"v1.{int(time.time())}.control",
            "worker_selector": {"hosts": ["qa-smoke.local"]},
            "spec": {"note": "control action smoke"},
        },
    )
    control_job_id = control_job["id"]
    cancelled_control = _json_request(
        "POST",
        f"/training/jobs/{control_job_id}/cancel",
        token=buyer_token,
        payload={"note": "qa smoke cancel"},
    )
    _assert(cancelled_control["status"] == "CANCELLED", "control job did not enter CANCELLED")

    retried_control = _json_request(
        "POST",
        f"/training/jobs/{control_job_id}/retry",
        token=buyer_token,
        payload={"note": "qa smoke retry"},
    )
    _assert(retried_control["status"] == "PENDING", "control job did not return to PENDING after retry")
    _assert(retried_control["assigned_worker_code"] in (None, ""), "control job did not clear assigned worker on retry")

    reassigned_control = _json_request(
        "POST",
        f"/training/jobs/{control_job_id}/reassign",
        token=buyer_token,
        payload={"worker_code": worker_code, "worker_host": "qa-smoke.local", "note": "qa smoke reassign"},
    )
    control_selector = reassigned_control.get("worker_selector") or {}
    _assert(reassigned_control["status"] == "PENDING", "control job did not stay PENDING after reassign")
    _assert(worker_code in (control_selector.get("worker_codes") or []), "control job reassign did not pin worker_code")
    _assert("qa-smoke.local" in (control_selector.get("hosts") or []), "control job reassign did not pin worker host")

    control_pull = _json_request(
        "POST",
        "/training/workers/pull-jobs",
        payload={"limit": 5},
        extra_headers=worker_headers,
    )
    assigned_control = next((row for row in control_pull["jobs"] if row["id"] == control_job_id), None)
    _assert(assigned_control is not None, "reassigned control job was not assigned to QA worker")
    control_signal_before_cancel = _json_request(
        "GET",
        f"/training/workers/job-control?{parse.urlencode({'job_id': control_job_id})}",
        extra_headers=worker_headers,
    )
    _assert(control_signal_before_cancel["should_stop"] is False, "assigned control job should not request stop before cancel")

    cancelled_assigned_control = _json_request(
        "POST",
        f"/training/jobs/{control_job_id}/cancel",
        token=buyer_token,
        payload={"note": "qa smoke cancel after assign"},
    )
    _assert(cancelled_assigned_control["status"] == "CANCELLED", "assigned control job did not cancel successfully")
    control_signal_after_cancel = _json_request(
        "GET",
        f"/training/workers/job-control?{parse.urlencode({'job_id': control_job_id})}",
        extra_headers=worker_headers,
    )
    _assert(control_signal_after_cancel["should_stop"] is True, "cancelled control job did not send stop signal")
    _assert(control_signal_after_cancel["status"] == "CANCELLED", "cancelled control job stop signal status mismatch")

    audit_checks = {
        "TRAINING_JOB_CREATE": _query_audit(admin_token, "TRAINING_JOB_CREATE", resource_id=job_id),
        "TRAINING_JOB_ASSIGN": _query_audit(admin_token, "TRAINING_JOB_ASSIGN", resource_id=job_id),
        "TRAINING_JOB_UPDATE": _query_audit(admin_token, "TRAINING_JOB_UPDATE", resource_id=job_id),
        "TRAINING_ASSET_PULL": _query_audit(admin_token, "TRAINING_ASSET_PULL", resource_id=job_id),
        "TRAINING_MODEL_PULL": _query_audit(admin_token, "TRAINING_MODEL_PULL", resource_id=job_id),
        "TRAINING_CANDIDATE_UPLOAD": _query_audit(admin_token, "TRAINING_CANDIDATE_UPLOAD", resource_id=job_id),
        "TRAINING_WORKER_REGISTER": _query_audit(admin_token, "TRAINING_WORKER_REGISTER", resource_id=worker["id"]),
        "TRAINING_WORKER_HEARTBEAT": _query_audit(admin_token, "TRAINING_WORKER_HEARTBEAT", limit=30),
    }
    control_audit_checks = {
        "TRAINING_JOB_CANCEL": _query_audit(admin_token, "TRAINING_JOB_CANCEL", resource_id=control_job_id),
        "TRAINING_JOB_RETRY": _query_audit(admin_token, "TRAINING_JOB_RETRY", resource_id=control_job_id),
        "TRAINING_JOB_REASSIGN": _query_audit(admin_token, "TRAINING_JOB_REASSIGN", resource_id=control_job_id),
    }
    _assert(len(audit_checks["TRAINING_JOB_CREATE"]) >= 1, "missing TRAINING_JOB_CREATE audit log")
    _assert(len(audit_checks["TRAINING_JOB_ASSIGN"]) >= 1, "missing TRAINING_JOB_ASSIGN audit log")
    _assert(len(audit_checks["TRAINING_JOB_UPDATE"]) >= 2, "missing TRAINING_JOB_UPDATE audit logs")
    _assert(len(audit_checks["TRAINING_ASSET_PULL"]) >= 2, "missing TRAINING_ASSET_PULL audit logs")
    _assert(len(audit_checks["TRAINING_MODEL_PULL"]) >= 1, "missing TRAINING_MODEL_PULL audit log")
    _assert(len(audit_checks["TRAINING_CANDIDATE_UPLOAD"]) >= 1, "missing TRAINING_CANDIDATE_UPLOAD audit log")
    _assert(len(audit_checks["TRAINING_WORKER_REGISTER"]) >= 1, "missing TRAINING_WORKER_REGISTER audit log")
    _assert(len(control_audit_checks["TRAINING_JOB_CANCEL"]) >= 2, "missing TRAINING_JOB_CANCEL audit logs")
    _assert(len(control_audit_checks["TRAINING_JOB_RETRY"]) >= 1, "missing TRAINING_JOB_RETRY audit log")
    _assert(len(control_audit_checks["TRAINING_JOB_REASSIGN"]) >= 1, "missing TRAINING_JOB_REASSIGN audit log")
    heartbeat_logs = [
        row for row in audit_checks["TRAINING_WORKER_HEARTBEAT"] if (row.get("detail") or {}).get("worker_code") == worker_code
    ]
    _assert(len(heartbeat_logs) >= 1, "missing TRAINING_WORKER_HEARTBEAT audit log for QA worker")

    report["checks"]["training_control_plane"] = {
        "worker_code": worker_code,
        "job_id": job_id,
        "job_code": job["job_code"],
        "base_model_id": base_model["id"],
        "candidate_model_id": candidate_model["id"],
        "candidate_model_code": candidate_model["model_code"],
        "candidate_model_version": candidate_model["version"],
        "empty_asset_job_id": empty_job["id"],
        "control_job_id": control_job_id,
        "audit_counts": {key: len(value) if isinstance(value, list) else 0 for key, value in audit_checks.items()},
        "control_audit_counts": {key: len(value) if isinstance(value, list) else 0 for key, value in control_audit_checks.items()},
        "control_signal": {
            "before_cancel_should_stop": control_signal_before_cancel["should_stop"],
            "after_cancel_should_stop": control_signal_after_cancel["should_stop"],
            "after_cancel_status": control_signal_after_cancel["status"],
        },
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _write_json(report_dir / f"training_control_plane_smoke_{timestamp}.json", report)
    _write_json(report_dir / "training_control_plane_latest.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run runtime smoke for the training control plane.")
    parser.add_argument("--report-dir", default=str(ROOT / "docs" / "qa" / "reports"))
    args = parser.parse_args()

    try:
        report = run_smoke(Path(args.report_dir))
    except CheckFailure as exc:
        failure = {
            "status": "failed",
            "meta": {"generated_at": _utc_now_iso(), "api_base": API_BASE},
            "error": str(exc),
        }
        report_dir = Path(args.report_dir)
        _write_json(report_dir / "training_control_plane_latest.json", failure)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _write_json(report_dir / f"training_control_plane_smoke_{timestamp}.json", failure)
        print(f"[fail] {exc}")
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("[ok] training control plane smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
