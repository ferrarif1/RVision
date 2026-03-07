#!/usr/bin/env python3
"""Runtime smoke checks for the VisionHub quick-detect flow."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_DIR = ROOT / "docs" / "qa" / "reports"
FIXTURE_PATH = ROOT / "docs" / "qa" / "fixtures" / "bus.jpg"
API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")
QUICK_DETECT_SAMPLE_URL = "https://raw.githubusercontent.com/ultralytics/yolov5/master/data/images/bus.jpg"


class CheckFailure(RuntimeError):
    """Raised when a quick-detect smoke check fails."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_request(method: str, path: str, payload: dict | None = None, token: str | None = None, timeout: int = 45) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = request.Request(url=f"{API_BASE}{path}", method=method, data=body, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return exc.code, parsed


def _binary_request(method: str, path: str, token: str | None = None, timeout: int = 45) -> tuple[int, bytes, dict[str, str]]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url=f"{API_BASE}{path}", method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


def _multipart_body(fields: dict[str, str], file_name: str, file_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----rvquick{uuid.uuid4().hex}"
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


def _upload_request(token: str, file_name: str, file_bytes: bytes, content_type: str) -> tuple[int, dict]:
    body, boundary = _multipart_body(
        fields={
            "sensitivity_level": "L2",
            "asset_purpose": "inference",
            "dataset_label": "quick-detect-smoke",
            "use_case": "quick-detect-smoke",
            "intended_model_code": "object_detect",
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


def _ensure_fixture() -> bytes:
    if FIXTURE_PATH.exists() and FIXTURE_PATH.stat().st_size > 0:
        return FIXTURE_PATH.read_bytes()

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    req = request.Request(QUICK_DETECT_SAMPLE_URL, headers={"User-Agent": "VisionHub-QA"})
    with request.urlopen(req, timeout=45) as resp:
        payload = resp.read()
    _assert(payload, "downloaded quick-detect sample is empty")
    FIXTURE_PATH.write_bytes(payload)
    return payload


def run_smoke(report_dir: Path) -> dict:
    report = {
        "status": "ok",
        "meta": {
            "generated_at": _now_iso(),
            "api_base": API_BASE,
            "fixture_path": str(FIXTURE_PATH),
        },
        "checks": {},
    }

    status_code, login = _json_request("POST", "/auth/login", {"username": "buyer_operator", "password": "buyer123"})
    _assert(status_code == 200, "buyer login failed")
    token = login.get("access_token") or ""
    _assert(token, "buyer login did not return access_token")

    fixture_bytes = _ensure_fixture()
    status_code, upload = _upload_request(token, f"quick_detect_{uuid.uuid4().hex[:8]}.jpg", fixture_bytes, "image/jpeg")
    _assert(status_code == 200, "quick-detect sample upload failed")
    asset_id = upload.get("id") or ""
    _assert(asset_id, "quick-detect upload did not return asset id")
    report["checks"]["fixture_upload"] = {
        "status_code": status_code,
        "asset_id": asset_id,
        "asset_type": upload.get("asset_type"),
    }

    status_code, recommendation = _json_request(
        "POST",
        "/tasks/recommend-model",
        {
            "asset_id": asset_id,
            "task_type": "object_detect",
            "device_code": "edge-01",
            "intent_text": "bus",
            "limit": 3,
        },
        token,
    )
    _assert(status_code == 200, "quick-detect model recommendation failed")
    selected_model = recommendation.get("selected_model") or {}
    _assert(selected_model.get("task_type") == "object_detect", "recommended model is not object_detect")
    report["checks"]["recommendation"] = {
        "selected_model": selected_model,
        "confidence": recommendation.get("confidence"),
        "summary": recommendation.get("summary"),
    }

    status_code, created = _json_request(
        "POST",
        "/tasks/create",
        {
            "asset_id": asset_id,
            "task_type": "object_detect",
            "device_code": "edge-01",
            "use_master_scheduler": True,
            "intent_text": "bus",
            "context": {"object_prompt": "bus"},
            "options": {"object_prompt": "bus"},
            "policy": {
                "upload_raw_video": False,
                "upload_frames": True,
                "desensitize_frames": False,
                "retention_days": 30,
                "quick_detect": {"object_prompt": "bus"},
            },
        },
        token,
    )
    _assert(status_code == 200, "quick-detect task creation failed")
    task_id = created.get("id") or ""
    _assert(task_id, "quick-detect task did not return task id")

    latest_task = None
    results: list[dict] = []
    deadline = datetime.now(timezone.utc).timestamp() + 120
    while datetime.now(timezone.utc).timestamp() < deadline:
        status_code, latest_task = _json_request("GET", f"/tasks/{task_id}", token=token)
        _assert(status_code == 200, "task detail query failed during quick-detect polling")
        status_code, result_rows = _json_request("GET", f"/results?task_id={task_id}", token=token)
        _assert(status_code == 200, "result query failed during quick-detect polling")
        results = result_rows if isinstance(result_rows, list) else []
        if results:
            break
        if latest_task.get("status") in {"FAILED", "CANCELLED"}:
            raise CheckFailure(latest_task.get("error_message") or f"quick-detect task failed: {latest_task.get('status')}")
        time.sleep(2)

    _assert(results, f"quick-detect task {task_id} produced no results")
    focus = next((row for row in results if (row.get("result_json") or {}).get("stage") == "expert"), results[0])
    result_json = focus.get("result_json") or {}
    predictions = result_json.get("predictions") or []
    matched_labels = set(result_json.get("matched_labels") or [])
    if not matched_labels:
        matched_labels.update(str(pred.get("label")) for pred in predictions if pred.get("label"))

    _assert(result_json.get("task_type") == "object_detect", "quick-detect result task_type mismatch")
    _assert(result_json.get("object_prompt") == "bus", "quick-detect result prompt mismatch")
    _assert(int(result_json.get("object_count") or len(predictions)) >= 1, "quick-detect produced no matched objects")
    _assert("bus" in matched_labels, "quick-detect did not detect the requested bus label")

    report["checks"]["quick_detect"] = {
        "task_id": task_id,
        "task_status": latest_task.get("status") if latest_task else None,
        "result_id": focus.get("id"),
        "object_prompt": result_json.get("object_prompt"),
        "object_count": result_json.get("object_count"),
        "matched_labels": sorted(matched_labels),
    }

    reviewed_predictions = list(predictions)
    first_bbox = (reviewed_predictions[0] or {}).get("bbox") if reviewed_predictions else None
    _assert(isinstance(first_bbox, list) and len(first_bbox) == 4, "quick-detect result did not provide a valid bbox for review")
    reviewed_predictions = [
        {
            "label": "bus_confirmed",
            "score": 0.99,
            "bbox": first_bbox,
            "attributes": {"review_source": "manual"},
        }
    ]
    status_code, reviewed = _json_request(
        "POST",
        f"/results/{focus.get('id')}/review",
        {"predictions": reviewed_predictions, "note": "quick-detect smoke review"},
        token,
    )
    _assert(status_code == 200, "quick-detect review save failed")
    reviewed_result = reviewed.get("result") or {}
    reviewed_json = reviewed_result.get("result_json") or {}
    reviewed_labels = set(reviewed_json.get("matched_labels") or [])
    if not reviewed_labels:
        reviewed_labels.update(str(pred.get("label")) for pred in (reviewed_json.get("predictions") or []) if pred.get("label"))
    _assert(reviewed_json.get("review_status") == "revised", "reviewed result did not enter revised state")
    _assert("bus_confirmed" in reviewed_labels, "reviewed result missing revised label")
    _assert(isinstance(reviewed_json.get("auto_predictions"), list) and reviewed_json.get("auto_predictions"), "reviewed result did not preserve auto_predictions")
    report["checks"]["review_save"] = {
        "result_id": reviewed_result.get("id"),
        "review_status": reviewed_json.get("review_status"),
        "matched_labels": sorted(reviewed_labels),
        "prediction_count": len(reviewed_json.get("predictions") or []),
    }

    status_code, exported = _json_request(
        "POST",
        "/results/export-dataset",
        {
            "task_ids": [task_id],
            "dataset_label": "quick-detect-smoke-dataset",
            "asset_purpose": "training",
            "include_screenshots": True,
        },
        token,
    )
    _assert(status_code == 200, "quick-detect dataset export failed")
    exported_asset = exported.get("asset") or {}
    exported_meta = exported_asset.get("meta") or {}
    _assert(exported_asset.get("asset_type") == "archive", "exported dataset asset type mismatch")
    _assert(exported_meta.get("archive_kind") == "result_annotation_bundle", "exported dataset archive kind mismatch")
    _assert(int(exported_meta.get("archive_resource_count") or 0) >= 1, "exported dataset resource count mismatch")
    _assert("bus_confirmed" in set(exported_meta.get("label_vocab") or []), "exported dataset missing reviewed label")
    dataset_version = exported.get("dataset_version") or {}
    _assert(dataset_version.get("id"), "dataset export did not return dataset_version id")
    _assert(dataset_version.get("asset_id") == exported_asset.get("id"), "dataset_version asset binding mismatch")
    report["checks"]["dataset_export"] = {
        "asset_id": exported_asset.get("id"),
        "file_name": exported_asset.get("file_name"),
        "archive_kind": exported_meta.get("archive_kind"),
        "archive_resource_count": exported_meta.get("archive_resource_count"),
        "label_vocab": exported_meta.get("label_vocab"),
        "dataset_version": dataset_version,
    }

    status_code, dataset_versions = _json_request("GET", "/assets/dataset-versions?limit=20", token=token)
    _assert(status_code == 200, "dataset version list query failed")
    matched_dataset_version = next((row for row in (dataset_versions or []) if row.get("id") == dataset_version.get("id")), None)
    _assert(matched_dataset_version is not None, "dataset version record not found in dataset version flow")
    report["checks"]["dataset_version_flow"] = {
        "dataset_version_id": matched_dataset_version.get("id"),
        "dataset_label": matched_dataset_version.get("dataset_label"),
        "version": matched_dataset_version.get("version"),
        "asset_id": matched_dataset_version.get("asset_id"),
    }

    status_code, recommended = _json_request(
        "POST",
        f"/assets/dataset-versions/{dataset_version.get('id')}/recommend",
        {"asset_purpose": "training", "note": "quick-detect smoke recommend"},
        token,
    )
    _assert(status_code == 200, "dataset version recommend failed")
    recommended_row = (recommended or {}).get("dataset_version") or {}
    recommended_summary = recommended_row.get("summary") or {}
    _assert(recommended_row.get("recommended") is True, "dataset version recommend did not set recommended flag")
    _assert(recommended_summary.get("recommended_for") == "training", "dataset version recommend target purpose mismatch")
    report["checks"]["dataset_version_recommend"] = {
        "dataset_version_id": recommended_row.get("id"),
        "recommended": recommended_row.get("recommended"),
        "recommended_for": recommended_summary.get("recommended_for"),
    }

    status_code, compared = _json_request(
        "GET",
        f"/assets/dataset-versions/compare?left_id={dataset_version.get('id')}&right_id={dataset_version.get('id')}",
        token=token,
    )
    _assert(status_code == 200, "dataset version compare failed")
    diff = (compared or {}).get("diff") or {}
    _assert(diff.get("same_dataset_key") is True, "dataset version compare same_dataset_key mismatch")
    report["checks"]["dataset_version_compare"] = {
        "same_dataset_key": diff.get("same_dataset_key"),
        "task_count_delta": diff.get("task_count_delta"),
        "resource_count_delta": diff.get("resource_count_delta"),
        "reviewed_task_count_delta": diff.get("reviewed_task_count_delta"),
    }

    status_code, preview = _json_request(
        "GET",
        f"/assets/dataset-versions/{dataset_version.get('id')}/preview?sample_limit=3",
        token=token,
    )
    _assert(status_code == 200, "dataset version preview failed")
    preview_samples = preview.get("samples") or []
    preview_manifest = preview.get("manifest") or {}
    _assert(preview.get("dataset_version", {}).get("id") == dataset_version.get("id"), "dataset version preview id mismatch")
    _assert(isinstance(preview_samples, list) and preview_samples, "dataset version preview returned no samples")
    report["checks"]["dataset_version_preview"] = {
        "dataset_version_id": preview.get("dataset_version", {}).get("id"),
        "sample_count": len(preview_samples),
        "manifest_task_count": preview_manifest.get("task_count"),
        "preview_sample_ids": [row.get("sample_id") for row in preview_samples],
    }

    preview_member = next((row.get("preview_file") for row in preview_samples if row.get("preview_file")), None)
    if preview_member:
        status_code, preview_blob, preview_headers = _binary_request(
            "GET",
            f"/assets/dataset-versions/{dataset_version.get('id')}/preview-file?member={parse.quote(preview_member, safe='')}",
            token=token,
        )
        _assert(status_code == 200, "dataset version preview file fetch failed")
        _assert(len(preview_blob) > 0, "dataset version preview file is empty")
        report["checks"]["dataset_version_preview_file"] = {
            "member": preview_member,
            "content_type": preview_headers.get("Content-Type") or preview_headers.get("content-type"),
            "size": len(preview_blob),
        }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _write_json(report_dir / f"quick_detect_smoke_{timestamp}.json", report)
    _write_json(report_dir / "quick_detect_latest.json", report)
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
                "fixture_path": str(FIXTURE_PATH),
            },
            "error": str(exc),
        }
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        _write_json(report_dir / "quick_detect_latest.json", failure)
        _write_json(report_dir / f"quick_detect_smoke_{timestamp}.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("[ok] quick detect smoke passed")


if __name__ == "__main__":
    main()
