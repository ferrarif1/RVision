#!/usr/bin/env python3
"""Batch runtime evaluation for railcar-number OCR samples."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "demo_data" / "generated_datasets" / "car_number_ocr_labeling" / "manifest.csv"
DEFAULT_REPORT_DIR = ROOT / "demo_data" / "generated_datasets" / "car_number_ocr_runtime_eval"
DEFAULT_SAMPLE_ROOTS = [
    ROOT / "demo_data" / "train",
    ROOT / "demo_data" / "validation",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_opener():
    return request.build_opener(request.ProxyHandler({}))


class EvalFailure(RuntimeError):
    """Raised when a runtime evaluation step fails."""


def _json_request(
    opener,
    api_base: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 60,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url=f"{api_base}{path}", method=method, data=body, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, json.loads(text) if text else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return exc.code, parsed


def _multipart_body(fields: dict[str, str], file_name: str, file_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----vistralcarocreval{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8"))
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _upload_asset(
    opener,
    api_base: str,
    *,
    token: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str = "image/jpeg",
) -> dict[str, Any]:
    body, boundary = _multipart_body(
        {
            "sensitivity_level": "L2",
            "asset_purpose": "inference",
            "dataset_label": "car-number-runtime-eval",
            "use_case": "car-number-runtime-eval",
            "intended_model_code": "car_number_ocr",
        },
        file_name,
        file_bytes,
        content_type,
    )
    req = request.Request(
        url=f"{api_base}/assets/upload",
        method="POST",
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with opener.open(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise EvalFailure(f"asset upload failed: {exc.code} {exc.read().decode('utf-8', errors='replace')}") from exc


def _login(opener, api_base: str, username: str, password: str) -> str:
    status, payload = _json_request(opener, api_base, "POST", "/auth/login", payload={"username": username, "password": password})
    if status != 200 or not payload.get("access_token"):
        raise EvalFailure(f"login failed: {status} {payload}")
    return str(payload["access_token"])


def _find_source_file(source_file: str) -> Path:
    for root in DEFAULT_SAMPLE_ROOTS:
        candidate = root / source_file
        if candidate.exists():
            return candidate
    fallback = ROOT / "demo_data" / source_file
    if fallback.exists():
        return fallback
    raise FileNotFoundError(source_file)


def _read_manifest(path: Path, limit: int) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    filtered = [row for row in rows if str(row.get("source_file") or "").strip()]
    return filtered[:limit] if limit > 0 else filtered


def _ground_truth_text(row: dict[str, str]) -> tuple[str, str]:
    final_text = str(row.get("final_text") or "").strip().upper()
    review_status = str(row.get("review_status") or "").strip().lower()
    if final_text and review_status == "done":
        return final_text, "final_text"
    suggestion = str(row.get("ocr_suggestion") or "").strip().upper()
    if suggestion:
        return suggestion, "ocr_suggestion"
    return "", "none"


def _poll_task(opener, api_base: str, token: str, task_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        status, payload = _json_request(opener, api_base, "GET", f"/tasks/{task_id}", token=token)
        if status != 200:
            raise EvalFailure(f"task poll failed: {status} {payload}")
        latest = payload
        if payload.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return latest
        time.sleep(1.0)
    raise EvalFailure(f"task poll timed out: {task_id}")


def _fetch_expert_result(opener, api_base: str, token: str, task_id: str) -> dict[str, Any]:
    status, rows = _json_request(opener, api_base, "GET", f"/results?task_id={task_id}", token=token, timeout=90)
    if status != 200 or not isinstance(rows, list):
        raise EvalFailure(f"result fetch failed: {status} {rows}")
    expert = next((row for row in rows if ((row.get("result_json") or {}).get("stage") == "expert")), None)
    if not expert:
        raise EvalFailure(f"expert result missing for task {task_id}")
    return expert


def _classify_issue(runtime_text: str, confidence: float | None, ground_truth: str) -> str:
    if not runtime_text:
        return "empty"
    if confidence is None or confidence < 0.6:
        return "low_confidence"
    if ground_truth and runtime_text != ground_truth:
        return "ground_truth_mismatch"
    if not ground_truth:
        return "no_ground_truth"
    return "ok"


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    opener = _build_opener()
    api_base = args.api_base.rstrip("/")
    token = _login(opener, api_base, args.username, args.password)
    rows = _read_manifest(Path(args.manifest), args.limit)
    report_rows: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        source_file = str(row.get("source_file") or "").strip()
        sample_result = {
            "index": index,
            "sample_id": row.get("sample_id"),
            "source_file": source_file,
            "task_id": None,
            "task_status": None,
            "selected_model_code": None,
            "runtime_text": "",
            "runtime_confidence": None,
            "runtime_engine": None,
            "runtime_bbox": None,
            "ground_truth_text": "",
            "ground_truth_source": "none",
            "manifest_suggestion": str(row.get("ocr_suggestion") or "").strip(),
            "manifest_engine": row.get("ocr_suggestion_engine"),
            "issue": "task_failed",
            "error": None,
        }
        try:
            sample_path = _find_source_file(source_file)
            ground_truth, ground_truth_source = _ground_truth_text(row)
            sample_result["ground_truth_text"] = ground_truth
            sample_result["ground_truth_source"] = ground_truth_source
            asset = _upload_asset(
                opener,
                api_base,
                token=token,
                file_name=(f"renamed_{uuid.uuid4().hex[:10]}{sample_path.suffix}" if args.rename_upload else sample_path.name),
                file_bytes=sample_path.read_bytes(),
                content_type="image/png" if sample_path.suffix.lower() == ".png" else "image/jpeg",
            )
            status, recommendation = _json_request(
                opener,
                api_base,
                "POST",
                "/tasks/recommend-model",
                token=token,
                payload={
                    "asset_id": asset["id"],
                    "task_type": "car_number_ocr",
                    "device_code": args.device_code,
                    "intent_text": "车号",
                    "limit": 3,
                },
            )
            if status != 200 or not recommendation.get("selected_model"):
                raise EvalFailure(f"recommend-model failed for {source_file}: {status} {recommendation}")
            selected = recommendation["selected_model"]
            sample_result["selected_model_code"] = selected.get("model_code")
            status, created = _json_request(
                opener,
                api_base,
                "POST",
                "/tasks/create",
                token=token,
                payload={
                    "asset_id": asset["id"],
                    "model_id": selected["model_id"],
                    "task_type": selected.get("task_type") or "car_number_ocr",
                    "device_code": args.device_code,
                    "use_master_scheduler": False,
                    "intent_text": "车号",
                    "policy": {
                        "upload_raw_video": False,
                        "upload_frames": True,
                        "desensitize_frames": False,
                        "retention_days": 30,
                        "quick_detect": {
                            "requested_task_type": "car_number_ocr",
                            "resolved_task_type": "car_number_ocr",
                            "eval_variant": args.variant,
                        },
                        "disable_curated_match": args.disable_curated_match,
                    },
                    "context": {},
                    "options": {},
                },
            )
            if status != 200:
                raise EvalFailure(f"task create failed for {source_file}: {status} {created}")
            sample_result["task_id"] = created["id"]
            task = _poll_task(opener, api_base, token, created["id"], args.wait_seconds)
            sample_result["task_status"] = task.get("status")
            if task.get("status") != "SUCCEEDED":
                raise EvalFailure(f"task finished with status {task.get('status')}: {task.get('error_message')}")
            expert = _fetch_expert_result(opener, api_base, token, created["id"])
            result_json = expert.get("result_json") or {}
            runtime_text = str(result_json.get("car_number") or "").strip()
            confidence_value = result_json.get("confidence")
            confidence = float(confidence_value) if isinstance(confidence_value, (int, float)) else None
            sample_result.update(
                {
                    "runtime_text": runtime_text,
                    "runtime_confidence": confidence,
                    "runtime_engine": result_json.get("engine"),
                    "runtime_bbox": result_json.get("bbox"),
                    "issue": _classify_issue(runtime_text, confidence, sample_result["ground_truth_text"]),
                }
            )
        except Exception as exc:
            sample_result["error"] = str(exc)
            if "timed out" in str(exc).lower():
                sample_result["issue"] = "timeout"
            elif sample_result["task_status"] == "FAILED":
                sample_result["issue"] = "task_failed"
        report_rows.append(sample_result)

    summary = {
        "generated_at": _utc_now_iso(),
        "api_base": api_base,
        "device_code": args.device_code,
        "variant": args.variant,
        "rename_upload": bool(args.rename_upload),
        "disable_curated_match": bool(args.disable_curated_match),
        "sample_count": len(report_rows),
        "issue_counts": {
            key: sum(1 for row in report_rows if row["issue"] == key)
            for key in ("ok", "ground_truth_mismatch", "low_confidence", "no_ground_truth", "empty", "timeout", "task_failed")
        },
        "rows": report_rows,
    }
    return summary


def _write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = re.sub(r"[^a-z0-9_-]+", "-", str(report.get("variant") or "default").lower()).strip("-") or "default"
    json_path = output_dir / f"car_number_runtime_eval_{suffix}_{stamp}.json"
    csv_path = output_dir / f"car_number_runtime_eval_{suffix}_{stamp}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "index",
            "sample_id",
            "source_file",
            "task_id",
            "task_status",
            "selected_model_code",
            "runtime_text",
            "runtime_confidence",
            "runtime_engine",
            "runtime_bbox",
            "ground_truth_text",
            "ground_truth_source",
            "manifest_suggestion",
            "manifest_engine",
            "issue",
            "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow(row)
    latest_path = output_dir / "latest.json"
    variant_latest_path = output_dir / f"latest_{suffix}.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    variant_latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "csv": str(csv_path), "latest": str(latest_path), "variant_latest": str(variant_latest_path)}, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate runtime railcar-number OCR samples against the live API.")
    parser.add_argument("--api-base", default=os.getenv("API_BASE", "http://localhost:8000"))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--device-code", default="edge-01")
    parser.add_argument("--username", default="buyer_operator")
    parser.add_argument("--password", default="buyer123")
    parser.add_argument("--limit", type=int, default=12, help="How many manifest rows to evaluate. Use 0 for all.")
    parser.add_argument("--wait-seconds", type=int, default=60)
    parser.add_argument("--variant", default="default", help="Logical evaluation variant name written into the report.")
    parser.add_argument("--rename-upload", action="store_true", help="Upload the same image bytes with randomized file names.")
    parser.add_argument("--disable-curated-match", action="store_true", help="Disable curated/fixture OCR shortcuts in runtime policy to probe true OCR generalization.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_eval(args)
    _write_report(report, Path(args.output_dir))


if __name__ == "__main__":
    main()
