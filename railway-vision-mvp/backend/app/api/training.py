import base64
import csv
import hashlib
import json
import os
import secrets
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.config import get_settings
from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import MODEL_STATUS_SUBMITTED
from app.core.constants import MODEL_TYPE_EXPERT
from app.core.constants import MODEL_TYPE_ROUTER
from app.core.constants import TRAINING_JOB_STATUS_CANCELLED
from app.core.constants import TRAINING_JOB_STATUS_DISPATCHED
from app.core.constants import TRAINING_JOB_STATUS_FAILED
from app.core.constants import TRAINING_JOB_STATUS_PENDING
from app.core.constants import TRAINING_JOB_STATUS_RUNNING
from app.core.constants import TRAINING_JOB_STATUS_SUCCEEDED
from app.core.constants import TRAINING_JOB_TERMINAL_STATUSES
from app.db.database import get_db
from app.db.models import DataAsset, DatasetVersion, ModelRecord, ModelRelease, Tenant, TrainingJob, TrainingWorker
from app.security.auth import hash_password
from app.security.dependencies import AuthUser, TrainingWorkerContext, get_training_worker, require_roles
from app.security.roles import (
    TRAINING_JOB_CREATE_ROLES,
    TRAINING_JOB_READ_ROLES,
    TRAINING_WORKER_READ_ROLES,
    TRAINING_WORKER_ADMIN_ROLES,
    is_buyer_user,
    is_platform_user,
    is_supplier_user,
)
from app.services.audit_service import record_audit
from app.services.dataset_version_service import create_dataset_version_record
from app.services.model_package_service import ModelPackageError, load_model_blobs, parse_and_validate_model_package, persist_model_package
from app.services.pipeline_service import normalize_model_inputs, normalize_model_outputs
from app.services.training_runtime_service import reconcile_training_runtime_health

router = APIRouter(prefix="/training", tags=["training"])

TRAINING_KIND_PATTERN = "^(train|finetune|evaluate)$"
WORKER_STATUS_PATTERN = "^(ACTIVE|INACTIVE|UNHEALTHY)$"
WORKER_UPDATE_STATUS_PATTERN = "^(RUNNING|SUCCEEDED|FAILED|CANCELLED)$"
MODEL_TYPE_PATTERN = "^(router|expert)$"
REVIEW_STATUS_PATTERN = "^(pending|done|needs_check)$"
REPO_ROOT = Path(__file__).resolve().parents[3]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class TrainingJobCreateRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, description="训练资产ID列表（0-n） / 0-n training asset IDs")
    validation_asset_ids: list[str] = Field(default_factory=list, description="验证资产ID列表（0-n） / 0-n validation asset IDs")
    base_model_id: str | None = Field(default=None, description="基线模型ID / Optional base model ID")
    owner_tenant_id: str | None = Field(default=None, description="模型归属租户ID / Owner tenant ID for candidate model")
    training_kind: str = Field(default="finetune", pattern=TRAINING_KIND_PATTERN, description="训练类型 / Training kind: train|finetune|evaluate")
    target_model_code: str = Field(description="目标模型编码 / Target model code")
    target_version: str = Field(description="目标模型版本 / Target model version")
    worker_selector: dict[str, Any] = Field(default_factory=dict, description="Worker 选择器 / Worker selector by code/label/resource")
    spec: dict[str, Any] = Field(default_factory=dict, description="训练规格 / Training spec payload")


class TrainingWorkerRegisterRequest(BaseModel):
    worker_code: str = Field(description="Worker 编码 / Unique worker code")
    name: str = Field(description="Worker 名称 / Worker display name")
    host: str | None = Field(default=None, description="Worker 主机地址 / Worker host or IP")
    status: str = Field(default="ACTIVE", pattern=WORKER_STATUS_PATTERN, description="Worker 状态 / Worker status")
    labels: dict[str, Any] = Field(default_factory=dict, description="Worker 标签 / Worker labels for scheduling")
    resources: dict[str, Any] = Field(default_factory=dict, description="Worker 资源信息 / Worker resources, e.g. gpu_mem_mb")


class TrainingWorkerHeartbeatRequest(BaseModel):
    host: str | None = Field(default=None, description="Worker 主机地址 / Worker host or IP")
    status: str = Field(default="ACTIVE", pattern=WORKER_STATUS_PATTERN, description="Worker 状态 / Worker status")
    labels: dict[str, Any] = Field(default_factory=dict, description="Worker 标签 / Worker labels")
    resources: dict[str, Any] = Field(default_factory=dict, description="Worker 资源信息 / Worker resource snapshot")


class TrainingWorkerPullJobsRequest(BaseModel):
    limit: int = Field(default=1, ge=1, le=5, description="拉取作业数量 / Number of jobs to pull")


class TrainingWorkerUpdateRequest(BaseModel):
    job_id: str = Field(description="训练作业ID / Training job ID")
    status: str = Field(pattern=WORKER_UPDATE_STATUS_PATTERN, description="作业状态 / Job status update")
    output_summary: dict[str, Any] = Field(default_factory=dict, description="输出摘要 / Structured output summary")
    error_message: str | None = Field(default=None, description="错误信息 / Optional error message")


class TrainingWorkerPullBaseModelRequest(BaseModel):
    job_id: str = Field(description="训练作业ID / Training job ID")


class TrainingJobActionRequest(BaseModel):
    note: str | None = Field(default=None, description="动作说明 / Optional operator note")


class TrainingJobReassignRequest(BaseModel):
    worker_code: str | None = Field(default=None, description="目标 Worker 编码 / Target worker code")
    worker_host: str | None = Field(default=None, description="目标 Worker 主机 / Target worker host or IP")
    note: str | None = Field(default=None, description="改派说明 / Optional reassign note")


class TrainingRuntimeReconcileRequest(BaseModel):
    note: str | None = Field(default=None, description="触发说明 / Optional reconcile note")
    worker_stale_seconds: int | None = Field(default=None, ge=1, description="本次 reconcile 的 worker stale 秒数覆盖 / Optional worker stale seconds override")
    dispatch_timeout_seconds: int | None = Field(default=None, ge=1, description="本次 reconcile 的 dispatch timeout 秒数覆盖 / Optional dispatch timeout override")
    running_timeout_seconds: int | None = Field(default=None, ge=1, description="本次 reconcile 的 running timeout 秒数覆盖 / Optional running timeout override")


class CarNumberLabelingReviewRequest(BaseModel):
    final_text: str | None = Field(default=None, description="人工确认后的车号文本 / Reviewed OCR text")
    review_status: str = Field(default="pending", pattern=REVIEW_STATUS_PATTERN, description="复核状态 / pending|done|needs_check")
    reviewer: str | None = Field(default=None, description="复核人 / Reviewer")
    notes: str | None = Field(default=None, description="备注 / Notes")


class CarNumberTextDatasetExportRequest(BaseModel):
    allow_suggestions: bool = Field(default=False, description="当 final_text 为空时，是否允许使用 ocr_suggestion / Allow OCR suggestion fallback")


class CarNumberTextDatasetAssetImportRequest(BaseModel):
    allow_suggestions: bool = Field(default=False, description="当 final_text 为空时，是否允许使用 ocr_suggestion / Allow OCR suggestion fallback")
    use_case: str = Field(default="railcar-number-ocr", description="业务场景 / Dataset use case")
    intended_model_code: str = Field(default="car_number_ocr", description="目标模型编码 / Intended target model code")
    sensitivity_level: str = Field(default="L2", description="敏感级别 / L1|L2|L3")


class CarNumberTextTrainingJobCreateRequest(CarNumberTextDatasetAssetImportRequest):
    training_kind: str = Field(default="finetune", pattern=TRAINING_KIND_PATTERN, description="训练类型 / train|finetune|evaluate")
    target_version: str | None = Field(default=None, description="目标版本；为空时自动生成 / Optional explicit target version")
    base_model_id: str | None = Field(default=None, description="基础模型 ID；为空时自动选择可见的同编码模型 / Optional base model ID")
    worker_code: str | None = Field(default=None, description="指定训练机编码 / Optional worker code")
    worker_host: str | None = Field(default=None, description="指定训练机 host / Optional worker host")
    spec: dict[str, Any] = Field(default_factory=dict, description="训练参数覆盖 / Optional spec overrides")


def _job_visible_to_user(job: TrainingJob, current_user: AuthUser) -> bool:
    if is_platform_user(current_user.roles):
        return True
    if is_supplier_user(current_user.roles):
        return bool(current_user.tenant_id and job.owner_tenant_id == current_user.tenant_id)
    if is_buyer_user(current_user.roles):
        return bool(current_user.tenant_id and job.buyer_tenant_id == current_user.tenant_id)
    return False


def _get_training_job_or_404(db: Session, job_id: str, current_user: AuthUser) -> TrainingJob:
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not job or not _job_visible_to_user(job, current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training job not found")
    return job


def _get_assets_or_400(db: Session, asset_ids: list[str]) -> list[DataAsset]:
    rows = db.query(DataAsset).filter(DataAsset.id.in_(asset_ids)).all()
    found = {row.id: row for row in rows}
    missing = [asset_id for asset_id in asset_ids if asset_id not in found]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Asset not found: {missing[0]}")
    return [found[asset_id] for asset_id in asset_ids]


def _normalize_asset_ids(asset_ids: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in asset_ids or []:
        cleaned = str(raw or "").strip()
        if not cleaned or cleaned in seen:
            continue
        ordered.append(cleaned)
        seen.add(cleaned)
    return ordered


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _car_number_labeling_dir() -> Path:
    override = str(os.getenv("CAR_NUMBER_LABELING_DIR") or "").strip()
    candidates = [Path(override)] if override else []
    candidates.extend(
        [
            REPO_ROOT / "demo_data" / "generated_datasets" / "car_number_ocr_labeling",
            Path("/app/demo_data/generated_datasets/car_number_ocr_labeling"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _car_number_labeling_manifest_path() -> Path:
    return _car_number_labeling_dir() / "manifest.csv"


def _car_number_labeling_jsonl_path() -> Path:
    return _car_number_labeling_dir() / "manifest.jsonl"


def _car_number_labeling_summary_path() -> Path:
    return _car_number_labeling_dir() / "summary.json"


def _car_number_text_dataset_dir() -> Path:
    override = str(os.getenv("CAR_NUMBER_TEXT_DATASET_DIR") or "").strip()
    candidates = [Path(override)] if override else []
    candidates.extend(
        [
            REPO_ROOT / "demo_data" / "generated_datasets" / "car_number_ocr_text_dataset",
            Path("/app/demo_data/generated_datasets/car_number_ocr_text_dataset"),
        ]
    )
    for candidate in candidates:
        parent = candidate.parent
        if candidate.exists() or parent.exists():
            return candidate
    return candidates[0]


def _car_number_text_dataset_summary_path() -> Path:
    return _car_number_text_dataset_dir() / "car_number_ocr_text_dataset_summary.json"


def _resolve_repo_relative_path(path_value: str | Path) -> Path:
    raw = Path(path_value)
    candidates = [raw]
    if not raw.is_absolute():
        candidates.extend([REPO_ROOT / raw, Path("/app") / raw])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _relative_repo_path(path: Path) -> str:
    resolved = path.resolve()
    for base in (Path("/app"), REPO_ROOT):
        try:
            return str(resolved.relative_to(base).as_posix())
        except Exception:
            continue
    try:
        return str(resolved.relative_to(REPO_ROOT).as_posix())
    except Exception:
        return str(path)


def _parse_json_or_none(value: str | None) -> dict[str, Any] | None:
    cleaned = _clean_optional(value)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON metadata field") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON metadata field must be an object")
    return parsed


def _load_car_number_labeling_rows() -> list[dict[str, str]]:
    manifest_path = _car_number_labeling_manifest_path()
    if not manifest_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Car-number labeling manifest not found")
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _rewrite_car_number_labeling_files(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Labeling manifest is empty")
    manifest_path = _car_number_labeling_manifest_path()
    jsonl_path = _car_number_labeling_jsonl_path()
    summary_path = _car_number_labeling_summary_path()
    fieldnames = list(rows[0].keys())
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    jsonl_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {}
    review_status_counts: dict[str, int] = {}
    final_text_count = 0
    suggestion_count = 0
    for row in rows:
        status_key = str(row.get("review_status") or "pending").strip() or "pending"
        review_status_counts[status_key] = review_status_counts.get(status_key, 0) + 1
        if str(row.get("final_text") or "").strip():
            final_text_count += 1
        if str(row.get("ocr_suggestion") or "").strip():
            suggestion_count += 1
    summary.update(
        {
            "status": "ok",
            "annotated_rows": len(rows),
            "suggestion_rows": suggestion_count,
            "suggestion_ratio": round((suggestion_count / len(rows)), 4) if rows else 0.0,
            "review_status_counts": review_status_counts,
            "final_text_rows": final_text_count,
            "final_text_ratio": round((final_text_count / len(rows)), 4) if rows else 0.0,
            "files": {
                "manifest_jsonl": "demo_data/generated_datasets/car_number_ocr_labeling/manifest.jsonl",
                "manifest_csv": "demo_data/generated_datasets/car_number_ocr_labeling/manifest.csv",
                "summary": "demo_data/generated_datasets/car_number_ocr_labeling/summary.json",
                "crops_dir": "demo_data/generated_datasets/car_number_ocr_labeling/crops",
            },
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _labeling_item_summary(row: dict[str, str]) -> dict[str, Any]:
    final_text = str(row.get("final_text") or "").strip()
    suggestion = str(row.get("ocr_suggestion") or "").strip()
    return {
        "sample_id": str(row.get("sample_id") or "").strip(),
        "split_hint": str(row.get("split_hint") or "").strip(),
        "source_file": str(row.get("source_file") or "").strip(),
        "crop_file": str(row.get("crop_file") or "").strip(),
        "label_class": str(row.get("label_class") or "").strip(),
        "review_status": str(row.get("review_status") or "pending").strip() or "pending",
        "reviewer": str(row.get("reviewer") or "").strip(),
        "notes": str(row.get("notes") or "").strip(),
        "final_text": final_text,
        "ocr_suggestion": suggestion,
        "ocr_suggestion_confidence": row.get("ocr_suggestion_confidence"),
        "ocr_suggestion_quality": row.get("ocr_suggestion_quality"),
        "ocr_suggestion_engine": row.get("ocr_suggestion_engine"),
        "bbox": [
            int(row.get("bbox_x1") or 0),
            int(row.get("bbox_y1") or 0),
            int(row.get("bbox_x2") or 0),
            int(row.get("bbox_y2") or 0),
        ],
        "has_final_text": bool(final_text),
        "has_suggestion": bool(suggestion),
    }


def _resolve_car_number_text(row: dict[str, str], *, allow_suggestions: bool) -> tuple[str, str]:
    final_text = str(row.get("final_text") or "").strip().upper()
    if final_text:
        return final_text, "final_text"
    if allow_suggestions:
        suggestion = str(row.get("ocr_suggestion") or "").strip().upper()
        if suggestion:
            return suggestion, "ocr_suggestion"
    return "", ""


def _write_car_number_text_bundle(
    *,
    rows: list[dict[str, str]],
    output_path: Path,
    split_name: str,
    dataset_label: str,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    dataset_key = f"local-car-number-ocr-text-{split_name}"
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            crop_rel = str(row.get("crop_file") or "").strip()
            crop_abs = _car_number_labeling_dir() / crop_rel
            if not crop_abs.exists():
                continue
            image_member = f"images/{Path(crop_rel).name}"
            zf.write(crop_abs, arcname=image_member)
            records.append(
                {
                    "sample_id": row.get("sample_id"),
                    "task_type": "car_number_ocr",
                    "label": row.get("label_class") or "number",
                    "text": row.get("resolved_text"),
                    "text_source": row.get("resolved_text_source"),
                    "image_file": image_member,
                    "preview_file": image_member,
                    "source_file_name": row.get("source_file"),
                    "source_file": row.get("crop_file"),
                    "object_prompt": row.get("resolved_text"),
                    "object_count": 1,
                    "matched_labels": [row.get("label_class") or "number"],
                    "split_hint": row.get("split_hint"),
                    "review_status": row.get("review_status"),
                    "bbox": [
                        int(row.get("bbox_x1") or 0),
                        int(row.get("bbox_y1") or 0),
                        int(row.get("bbox_x2") or 0),
                        int(row.get("bbox_y2") or 0),
                    ],
                }
            )
        manifest = {
            "dataset_key": dataset_key,
            "dataset_label": dataset_label,
            "task_type": "car_number_ocr",
            "split": split_name,
            "sample_count": len(records),
            "annotation_count": len(records),
            "annotation_format": "vistral_local_car_number_text_v1",
            "generated_at": datetime.utcnow().isoformat(),
            "source_manifest": "demo_data/generated_datasets/car_number_ocr_labeling/manifest.csv",
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        zf.writestr(
            "README.txt",
            "Vistral local car-number text dataset bundle\n"
            f"split={split_name}\n"
            f"samples={len(records)}\n"
            "images/ contains cropped number regions\n"
            "annotations/records.jsonl contains OCR text labels\n",
        )
        zf.writestr(
            "annotations/records.jsonl",
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        )
    return {
        "split": split_name,
        "dataset_label": dataset_label,
        "dataset_key": dataset_key,
        "zip_path": _relative_repo_path(output_path),
        "sample_count": len(records),
        "annotation_count": len(records),
    }


def _export_car_number_text_dataset(*, allow_suggestions: bool) -> dict[str, Any]:
    rows = _load_car_number_labeling_rows()
    accepted: list[dict[str, str]] = []
    skipped_missing_text = 0
    source_counts: dict[str, int] = {}
    for row in rows:
        text_value, text_source = _resolve_car_number_text(row, allow_suggestions=allow_suggestions)
        if not text_value:
            skipped_missing_text += 1
            continue
        item = dict(row)
        item["resolved_text"] = text_value
        item["resolved_text_source"] = text_source
        source_counts[text_source] = source_counts.get(text_source, 0) + 1
        accepted.append(item)
    if len(accepted) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough labeled rows to export OCR text dataset")
    train_rows = [row for row in accepted if str(row.get("split_hint") or "") == "train"]
    validation_rows = [row for row in accepted if str(row.get("split_hint") or "") == "validation"]
    if not train_rows or not validation_rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Need both train and validation rows to export OCR text dataset")
    output_dir = _car_number_text_dataset_dir()
    train_bundle = _write_car_number_text_bundle(
        rows=train_rows,
        output_path=output_dir / "car_number_ocr_text_train_bundle.zip",
        split_name="train",
        dataset_label="local-car-number-text-train",
    )
    validation_bundle = _write_car_number_text_bundle(
        rows=validation_rows,
        output_path=output_dir / "car_number_ocr_text_validation_bundle.zip",
        split_name="validation",
        dataset_label="local-car-number-text-validation",
    )
    summary = {
        "status": "ok",
        "generated_at": datetime.utcnow().isoformat(),
        "source_manifest": "demo_data/generated_datasets/car_number_ocr_labeling/manifest.csv",
        "output_dir": _relative_repo_path(output_dir),
        "accepted_rows": len(accepted),
        "skipped_missing_text": skipped_missing_text,
        "text_sources": source_counts,
        "bundles": {
            "train": train_bundle,
            "validation": validation_bundle,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "car_number_ocr_text_dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _copy_file_with_checksum(source_path: Path, target_path: Path) -> tuple[str, int]:
    checksum = hashlib.sha256()
    size = 0
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("rb") as source, target_path.open("wb") as target:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            checksum.update(chunk)
            target.write(chunk)
            size += len(chunk)
    return checksum.hexdigest(), size


def _inspect_local_dataset_archive(storage_path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(storage_path) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Generated OCR dataset bundle is invalid") from exc

    preview_members: list[str] = []
    image_count = 0
    file_count = 0
    directory_count = 0
    ignored_entry_count = 0
    max_depth = 0
    total_uncompressed_bytes = 0
    for info in infos:
        path = Path(str(info.filename or "").replace("\\", "/"))
        if info.is_dir() or str(info.filename).endswith("/"):
            directory_count += 1
            max_depth = max(max_depth, len(path.parts) - 1)
            continue
        file_count += 1
        max_depth = max(max_depth, len(path.parts) - 1)
        total_uncompressed_bytes += max(int(info.file_size or 0), 0)
        ext = path.suffix.lower()
        if ext in IMAGE_EXTENSIONS and str(info.filename).startswith("images/"):
            image_count += 1
            if len(preview_members) < 12:
                preview_members.append(str(info.filename))
        else:
            ignored_entry_count += 1
    return {
        "archive_kind": "zip_dataset",
        "archive_entry_count": len(infos),
        "archive_file_count": file_count,
        "archive_directory_count": directory_count,
        "archive_resource_count": image_count,
        "archive_image_count": image_count,
        "archive_video_count": 0,
        "archive_ignored_entry_count": ignored_entry_count,
        "archive_max_depth": max_depth,
        "archive_preview_members": preview_members,
        "archive_uncompressed_bytes": total_uncompressed_bytes,
    }


def _find_reusable_local_dataset_asset(
    db: Session,
    *,
    checksum: str,
    file_name: str,
    sensitivity_level: str,
    buyer_tenant_id: str | None,
    source_uri: str,
    meta: dict[str, Any],
) -> DataAsset | None:
    query = db.query(DataAsset).filter(
        DataAsset.checksum == checksum,
        DataAsset.file_name == file_name,
        DataAsset.asset_type == "archive",
        DataAsset.sensitivity_level == sensitivity_level,
    )
    if buyer_tenant_id:
        query = query.filter(DataAsset.buyer_tenant_id == buyer_tenant_id)
    else:
        query = query.filter(DataAsset.buyer_tenant_id.is_(None))
    for row in query.order_by(DataAsset.created_at.desc()).limit(8).all():
        row_meta = row.meta if isinstance(row.meta, dict) else {}
        if row.source_uri == source_uri and row_meta == meta:
            return row
    return None


def _register_car_number_text_dataset_asset(
    *,
    db: Session,
    current_user: AuthUser,
    request: Request,
    bundle_summary: dict[str, Any],
    export_summary: dict[str, Any],
    asset_purpose: str,
    use_case: str,
    intended_model_code: str,
    sensitivity_level: str,
) -> dict[str, Any]:
    source_bundle = _resolve_repo_relative_path(str(bundle_summary.get("zip_path") or ""))
    if not source_bundle.exists() or not source_bundle.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exported OCR dataset bundle file not found")
    if sensitivity_level not in {"L1", "L2", "L3"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sensitivity_level")

    settings = get_settings()
    os.makedirs(settings.asset_repo_path, exist_ok=True)
    asset_id = str(uuid.uuid4())
    ext = source_bundle.suffix or ".zip"
    target_path = Path(settings.asset_repo_path) / f"{asset_id}{ext}"
    checksum, file_size = _copy_file_with_checksum(source_bundle, target_path)
    dataset_label = str(bundle_summary.get("dataset_label") or f"local-car-number-text-{asset_purpose}").strip()
    source_uri = f"vistral://training/car-number-labeling/export-text-dataset/{asset_purpose}"
    meta = {
        "size": file_size,
        "extension": ext,
        "asset_purpose": asset_purpose,
        "dataset_label": dataset_label,
        "use_case": use_case,
        "intended_model_code": intended_model_code,
        "task_type": "car_number_ocr",
        "text_source_counts": export_summary.get("text_sources") or {},
        "generated_from": "car_number_labeling_review",
        "accepted_rows": export_summary.get("accepted_rows"),
        "split": bundle_summary.get("split"),
        **_inspect_local_dataset_archive(target_path),
    }
    buyer_tenant_id = current_user.tenant_id if is_buyer_user(current_user.roles) else None
    reusable_asset = _find_reusable_local_dataset_asset(
        db,
        checksum=checksum,
        file_name=source_bundle.name,
        sensitivity_level=sensitivity_level,
        buyer_tenant_id=buyer_tenant_id,
        source_uri=source_uri,
        meta=meta,
    )
    if reusable_asset:
        if target_path.exists():
            target_path.unlink()
        asset = reusable_asset
        reused = True
    else:
        asset = DataAsset(
            id=asset_id,
            file_name=source_bundle.name,
            asset_type="archive",
            storage_uri=str(target_path),
            source_uri=source_uri,
            sensitivity_level=sensitivity_level,
            checksum=checksum,
            buyer_tenant_id=buyer_tenant_id,
            meta=meta,
            uploaded_by=current_user.id,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        reused = False
        record_audit(
            db,
            action=actions.ASSET_UPLOAD,
            resource_type="asset",
            resource_id=asset.id,
            detail={
                "file_name": asset.file_name,
                "size": file_size,
                "asset_purpose": asset_purpose,
                "asset_type": asset.asset_type,
                "dataset_label": dataset_label,
                "use_case": use_case,
                "intended_model_code": intended_model_code,
                "generated_from": "car_number_labeling_review",
            },
            request=request,
            actor=current_user,
        )

    version_summary = {
        "task_type": "car_number_ocr",
        "resource_count": bundle_summary.get("sample_count") or 0,
        "task_count": bundle_summary.get("sample_count") or 0,
        "reviewed_task_count": bundle_summary.get("sample_count") or 0,
        "label_vocab": ["number"],
        "text_source_counts": export_summary.get("text_sources") or {},
        "generated_from": "car_number_labeling_review",
        "generated_at": export_summary.get("generated_at"),
        "accepted_rows": export_summary.get("accepted_rows"),
        "skipped_missing_text": export_summary.get("skipped_missing_text"),
    }
    dataset_version = create_dataset_version_record(
        db,
        asset=asset,
        dataset_label=dataset_label,
        dataset_key=str(bundle_summary.get("dataset_key") or dataset_label),
        asset_purpose=asset_purpose,
        source_type="ocr_text_export",
        summary=version_summary,
        created_by=current_user.id,
    )
    db.commit()
    db.refresh(dataset_version)
    db.refresh(asset)
    record_audit(
        db,
        action=actions.DATASET_VERSION_CREATE,
        resource_type="dataset_version",
        resource_id=dataset_version.id,
        detail={
            "dataset_key": dataset_version.dataset_key,
            "dataset_label": dataset_version.dataset_label,
            "version": dataset_version.version,
            "asset_id": asset.id,
            "asset_purpose": asset_purpose,
            "source_type": "ocr_text_export",
        },
        request=request,
        actor=current_user,
    )
    return {
        "asset_id": asset.id,
        "dataset_version_id": dataset_version.id,
        "dataset_label": dataset_version.dataset_label,
        "dataset_key": dataset_version.dataset_key,
        "version": dataset_version.version,
        "asset_purpose": asset_purpose,
        "reused_asset": reused,
    }


def _export_car_number_text_assets_internal(
    *,
    payload: CarNumberTextDatasetAssetImportRequest,
    request: Request,
    db: Session,
    current_user: AuthUser,
) -> dict[str, Any]:
    export_summary = _export_car_number_text_dataset(allow_suggestions=payload.allow_suggestions)
    intended_model_code = str(payload.intended_model_code or "").strip() or "car_number_ocr"
    use_case = str(payload.use_case or "").strip() or "railcar-number-ocr"
    train_bundle = export_summary.get("bundles", {}).get("train") or {}
    validation_bundle = export_summary.get("bundles", {}).get("validation") or {}
    train_asset = _register_car_number_text_dataset_asset(
        db=db,
        current_user=current_user,
        request=request,
        bundle_summary=train_bundle,
        export_summary=export_summary,
        asset_purpose="training",
        use_case=use_case,
        intended_model_code=intended_model_code,
        sensitivity_level=payload.sensitivity_level,
    )
    validation_asset = _register_car_number_text_dataset_asset(
        db=db,
        current_user=current_user,
        request=request,
        bundle_summary=validation_bundle,
        export_summary=export_summary,
        asset_purpose="validation",
        use_case=use_case,
        intended_model_code=intended_model_code,
        sensitivity_level=payload.sensitivity_level,
    )
    return {
        "status": "ok",
        "export": export_summary,
        "training_asset": train_asset,
        "validation_asset": validation_asset,
        "prefill": {
            "train_asset_ids": [train_asset["asset_id"]],
            "validation_asset_ids": [validation_asset["asset_id"]],
            "dataset_label": train_asset["dataset_label"],
            "training_dataset_version_id": train_asset["dataset_version_id"],
            "validation_dataset_version_id": validation_asset["dataset_version_id"],
            "intended_model_code": intended_model_code,
        },
    }


def _buyer_can_use_model(base_model: ModelRecord, current_user: AuthUser, db: Session) -> bool:
    if not is_buyer_user(current_user.roles):
        return True
    releases = (
        db.query(ModelRelease)
        .filter(ModelRelease.model_id == base_model.id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .all()
    )
    buyer_code = current_user.tenant_code
    for release in releases:
        targets = release.target_buyers or []
        if not targets or (buyer_code and buyer_code in targets):
            return True
    return False


def _resolve_default_base_model(
    *,
    db: Session,
    current_user: AuthUser,
    intended_model_code: str,
    base_model_id: str | None,
) -> ModelRecord | None:
    if base_model_id:
        base_model = db.query(ModelRecord).filter(ModelRecord.id == base_model_id).first()
        if not base_model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Base model not found")
        if not _buyer_can_use_model(base_model, current_user, db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Base model is not released to current buyer tenant")
        return base_model

    query = db.query(ModelRecord).filter(
        ModelRecord.model_type == MODEL_TYPE_EXPERT,
        ModelRecord.model_code == intended_model_code,
    )
    candidates = query.order_by(ModelRecord.created_at.desc()).all()
    for candidate in candidates:
        if _buyer_can_use_model(candidate, current_user, db):
            return candidate
    return None


def _default_car_number_training_spec(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {
        "trainer": "car_number_ocr_local",
        "epochs": 8,
        "learning_rate": 0.0005,
        "batch_size": 16,
        "image_size": [192, 64],
        "text_head": "ctc",
        "augmentation": {
            "motion_blur": 0.15,
            "brightness": 0.2,
            "contrast": 0.2,
            "perspective": 0.12,
        },
    }
    if not isinstance(overrides, dict):
        return base
    merged = dict(base)
    for key, value in overrides.items():
        if key == "augmentation" and isinstance(value, dict) and isinstance(merged.get("augmentation"), dict):
            merged["augmentation"] = {**merged["augmentation"], **value}
        else:
            merged[key] = value
    return merged


def _auto_target_version(model_code: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d.%H%M%S")
    suffix = hashlib.sha1(f"{model_code}:{timestamp}".encode("utf-8")).hexdigest()[:4]
    return f"v{timestamp}.{suffix}"

def _ensure_single_buyer_scope(rows: list[DataAsset]) -> str | None:
    buyer_ids = {row.buyer_tenant_id for row in rows if row.buyer_tenant_id}
    if len(buyer_ids) > 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Training assets must belong to one buyer tenant")
    return next(iter(buyer_ids), None)


def _model_summary(model: ModelRecord | None) -> dict[str, Any] | None:
    if not model:
        return None
    return {
        "id": model.id,
        "model_code": model.model_code,
        "version": model.version,
        "model_hash": model.model_hash,
        "model_type": model.model_type,
        "runtime": model.runtime,
        "plugin_name": model.plugin_name,
    }


def _job_alert_summary(job: TrainingJob) -> tuple[str | None, str | None, str | None]:
    summary = job.output_summary if isinstance(job.output_summary, dict) else {}
    alert_level = str(summary.get("alert_level") or "").strip() or None
    alert_reason = str(summary.get("alert_reason") or summary.get("failure_category") or job.error_message or "").strip() or None
    recommended_action = str(summary.get("recommended_action") or "").strip() or None
    return alert_level, alert_reason, recommended_action


def _asset_summary(asset: DataAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "file_name": asset.file_name,
        "asset_type": asset.asset_type,
        "sensitivity_level": asset.sensitivity_level,
        "storage_uri": asset.storage_uri,
        "meta": asset.meta if isinstance(asset.meta, dict) else {},
    }


def _serialize_job(db: Session, job: TrainingJob) -> dict[str, Any]:
    base_model = db.query(ModelRecord).filter(ModelRecord.id == job.base_model_id).first() if job.base_model_id else None
    candidate_model = db.query(ModelRecord).filter(ModelRecord.id == job.candidate_model_id).first() if job.candidate_model_id else None
    owner_tenant = db.query(Tenant).filter(Tenant.id == job.owner_tenant_id).first() if job.owner_tenant_id else None
    buyer_tenant = db.query(Tenant).filter(Tenant.id == job.buyer_tenant_id).first() if job.buyer_tenant_id else None
    alert_level, alert_reason, recommended_action = _job_alert_summary(job)
    return {
        "id": job.id,
        "job_code": job.job_code,
        "status": job.status,
        "training_kind": job.training_kind,
        "target_model_code": job.target_model_code,
        "target_version": job.target_version,
        "asset_ids": job.asset_ids or [],
        "asset_count": len(job.asset_ids or []),
        "validation_asset_ids": job.validation_asset_ids or [],
        "validation_asset_count": len(job.validation_asset_ids or []),
        "base_model": _model_summary(base_model),
        "candidate_model": _model_summary(candidate_model),
        "owner_tenant_id": job.owner_tenant_id,
        "owner_tenant_code": owner_tenant.tenant_code if owner_tenant else None,
        "buyer_tenant_id": job.buyer_tenant_id,
        "buyer_tenant_code": buyer_tenant.tenant_code if buyer_tenant else None,
        "worker_selector": job.worker_selector or {},
        "assigned_worker_code": job.assigned_worker_code,
        "spec": job.spec or {},
        "output_summary": job.output_summary or {},
        "error_message": job.error_message,
        "alert_level": alert_level,
        "alert_reason": alert_reason,
        "recommended_action": recommended_action,
        "dispatch_count": job.dispatch_count,
        "can_cancel": job.status not in TRAINING_JOB_TERMINAL_STATUSES,
        "can_retry": job.status in {TRAINING_JOB_STATUS_FAILED, TRAINING_JOB_STATUS_CANCELLED} and not bool(job.candidate_model_id),
        "can_reassign": job.status in {TRAINING_JOB_STATUS_PENDING, TRAINING_JOB_STATUS_DISPATCHED, TRAINING_JOB_STATUS_FAILED, TRAINING_JOB_STATUS_CANCELLED} and not (job.status in TRAINING_JOB_TERMINAL_STATUSES and bool(job.candidate_model_id)),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _serialize_worker(db: Session, worker: TrainingWorker) -> dict[str, Any]:
    pending_count = (
        db.query(TrainingJob)
        .filter(
            TrainingJob.assigned_worker_code == worker.worker_code,
            TrainingJob.status.in_((TRAINING_JOB_STATUS_DISPATCHED, TRAINING_JOB_STATUS_RUNNING)),
        )
        .count()
    )
    return {
        "id": worker.id,
        "worker_code": worker.worker_code,
        "name": worker.name,
        "status": worker.status,
        "host": worker.host,
        "labels": worker.labels or {},
        "resources": worker.resources or {},
        "last_seen_at": worker.last_seen_at,
        "heartbeat_age_sec": int((datetime.utcnow() - worker.last_seen_at).total_seconds()) if worker.last_seen_at else None,
        "alert_level": "CRITICAL" if worker.status == "UNHEALTHY" else None,
        "alert_reason": "Worker heartbeat stale or manually marked unhealthy" if worker.status == "UNHEALTHY" else None,
        "last_job_at": worker.last_job_at,
        "outstanding_jobs": pending_count,
        "created_at": worker.created_at,
    }


def _worker_matches_selector(job: TrainingJob, worker: TrainingWorker) -> bool:
    selector = job.worker_selector if isinstance(job.worker_selector, dict) else {}
    if not selector:
        return True

    worker_codes = selector.get("worker_codes")
    if isinstance(worker_codes, list) and worker_codes and worker.worker_code not in worker_codes:
        return False

    worker_host = str(worker.host or "").strip().lower()
    requested_hosts: list[str] = []
    hosts = selector.get("hosts")
    if isinstance(hosts, list):
        requested_hosts.extend(str(item or "").strip().lower() for item in hosts if str(item or "").strip())
    host = selector.get("host")
    if str(host or "").strip():
        requested_hosts.append(str(host).strip().lower())
    if requested_hosts and worker_host not in requested_hosts:
        return False

    labels = selector.get("labels")
    worker_labels = worker.labels if isinstance(worker.labels, dict) else {}
    if isinstance(labels, dict):
        for key, expected in labels.items():
            if worker_labels.get(key) != expected:
                return False

    min_gpu_mem_mb = selector.get("min_gpu_mem_mb")
    worker_gpu_mem = (worker.resources or {}).get("gpu_mem_mb")
    if isinstance(min_gpu_mem_mb, int) and isinstance(worker_gpu_mem, int) and worker_gpu_mem < min_gpu_mem_mb:
        return False

    return True


def _get_worker_job_or_403(db: Session, worker_code: str, job_id: str) -> TrainingJob:
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training job not found")
    if not job.assigned_worker_code or job.assigned_worker_code != worker_code:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Training job assigned to a different worker")
    return job


def _control_note(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _ensure_retryable(job: TrainingJob, action_name: str) -> None:
    if job.candidate_model_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Training job already linked a candidate model, cannot {action_name}",
        )


def _resolve_target_worker(db: Session, worker_code: str | None, worker_host: str | None) -> tuple[TrainingWorker | None, str | None, str | None]:
    clean_code = _clean_optional(worker_code)
    clean_host = _clean_optional(worker_host)
    if not clean_code and not clean_host:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="worker_code or worker_host is required")

    target_worker = None
    if clean_code:
        target_worker = db.query(TrainingWorker).filter(TrainingWorker.worker_code == clean_code).first()
        if not target_worker:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target worker not found")
        if target_worker.status != "ACTIVE":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target worker is not ACTIVE")
        if clean_host and str(target_worker.host or "").strip().lower() != clean_host.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="worker_code does not match worker_host")
        clean_host = clean_host or _clean_optional(target_worker.host)
    elif clean_host:
        target_worker = next(
            (
                row
                for row in db.query(TrainingWorker).all()
                if row.status == "ACTIVE" and str(row.host or "").strip().lower() == clean_host.lower()
            ),
            None,
        )
    return target_worker, clean_code, clean_host


def _platform_meta_for_candidate(job: TrainingJob, base_model: ModelRecord | None, dataset_label: str | None, training_round: str | None, training_summary: str | None) -> dict[str, Any]:
    base_model_ref = None
    if base_model:
        base_model_ref = f"{base_model.model_code}:{base_model.version}"
    meta = {
        "model_source_type": "finetuned_candidate",
        "base_model_ref": base_model_ref,
        "training_round": training_round,
        "dataset_label": dataset_label,
        "training_summary": training_summary,
        "training_job_id": job.id,
        "training_job_code": job.job_code,
        "buyer_tenant_id": job.buyer_tenant_id,
        "owner_tenant_id": job.owner_tenant_id,
    }
    return {key: value for key, value in meta.items() if value not in (None, "", [], {})}


@router.post("/jobs")
def create_training_job(
    payload: TrainingJobCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    train_asset_ids = _normalize_asset_ids(payload.asset_ids)
    validation_asset_ids = _normalize_asset_ids(payload.validation_asset_ids)
    duplicated = set(train_asset_ids) & set(validation_asset_ids)
    if duplicated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Training and validation assets must not overlap: {next(iter(duplicated))}",
        )

    train_assets = _get_assets_or_400(db, train_asset_ids) if train_asset_ids else []
    validation_assets = _get_assets_or_400(db, validation_asset_ids) if validation_asset_ids else []
    # 关键约束：一次训练作业只能绑定同一个买家租户，避免跨租户数据混用。
    # Critical constraint: one training job must remain in a single buyer tenant scope.
    buyer_tenant_id = _ensure_single_buyer_scope([*train_assets, *validation_assets])
    if is_buyer_user(current_user.roles):
        if buyer_tenant_id and buyer_tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Buyer training job cannot reference a different tenant scope")
        buyer_tenant_id = current_user.tenant_id

    base_model = None
    owner_tenant_id = payload.owner_tenant_id
    if payload.base_model_id:
        base_model = db.query(ModelRecord).filter(ModelRecord.id == payload.base_model_id).first()
        if not base_model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Base model not found")
        if is_buyer_user(current_user.roles):
            releases = (
                db.query(ModelRelease)
                .filter(ModelRelease.model_id == base_model.id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
                .order_by(ModelRelease.created_at.desc())
                .all()
            )
            buyer_code = current_user.tenant_code
            allowed = False
            for release in releases:
                targets = release.target_buyers or []
                if not targets or (buyer_code and buyer_code in targets):
                    allowed = True
                    break
            if not allowed:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Base model is not released to current buyer tenant")
        if owner_tenant_id and base_model.owner_tenant_id and owner_tenant_id != base_model.owner_tenant_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="owner_tenant_id does not match base model owner")
        owner_tenant_id = base_model.owner_tenant_id or owner_tenant_id

    if owner_tenant_id:
        owner_tenant = db.query(Tenant).filter(Tenant.id == owner_tenant_id).first()
        if not owner_tenant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Owner tenant not found")

    job = TrainingJob(
        id=str(uuid.uuid4()),
        job_code=f"train-{uuid.uuid4().hex[:10]}",
        owner_tenant_id=owner_tenant_id,
        buyer_tenant_id=buyer_tenant_id,
        base_model_id=payload.base_model_id,
        status=TRAINING_JOB_STATUS_PENDING,
        training_kind=payload.training_kind,
        asset_ids=train_asset_ids,
        validation_asset_ids=validation_asset_ids,
        target_model_code=payload.target_model_code.strip(),
        target_version=payload.target_version.strip(),
        worker_selector=payload.worker_selector,
        spec=payload.spec,
        requested_by=current_user.id,
    )
    db.add(job)
    db.commit()

    record_audit(
        db,
        action=actions.TRAINING_JOB_CREATE,
        resource_type="training_job",
        resource_id=job.id,
        detail={
            "job_code": job.job_code,
            "training_kind": job.training_kind,
            "base_model_id": job.base_model_id,
            "asset_ids": train_asset_ids,
            "validation_asset_ids": validation_asset_ids,
            "owner_tenant_id": owner_tenant_id,
            "buyer_tenant_id": buyer_tenant_id,
        },
        request=request,
        actor=current_user,
    )
    return _serialize_job(db, job)


@router.get("/jobs")
def list_training_jobs(
    status_filter: str | None = Query(default=None, alias="status", description="状态筛选 / Filter by training job status"),
    training_kind: str | None = Query(default=None, description="训练类型筛选 / Filter by training kind"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    reconcile_training_runtime_health(db)
    query = db.query(TrainingJob).order_by(TrainingJob.created_at.desc())
    if status_filter:
        query = query.filter(TrainingJob.status == status_filter)
    if training_kind:
        query = query.filter(TrainingJob.training_kind == training_kind)

    rows = query.all()
    visible = [row for row in rows if _job_visible_to_user(row, current_user)]
    return [_serialize_job(db, row) for row in visible]


@router.get("/car-number-labeling/summary")
def get_car_number_labeling_summary(
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    rows = _load_car_number_labeling_rows()
    summary_payload = {}
    summary_path = _car_number_labeling_summary_path()
    if summary_path.exists():
        try:
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary_payload = {}
    review_status_counts: dict[str, int] = {}
    final_text_rows = 0
    suggestion_rows = 0
    for row in rows:
        status_key = str(row.get("review_status") or "pending").strip() or "pending"
        review_status_counts[status_key] = review_status_counts.get(status_key, 0) + 1
        if str(row.get("final_text") or "").strip():
            final_text_rows += 1
        if str(row.get("ocr_suggestion") or "").strip():
            suggestion_rows += 1
    summary_payload.update(
        {
            "annotated_rows": len(rows),
            "review_status_counts": review_status_counts,
            "final_text_rows": final_text_rows,
            "final_text_ratio": round((final_text_rows / len(rows)), 4) if rows else 0.0,
            "suggestion_rows": suggestion_rows,
            "suggestion_ratio": round((suggestion_rows / len(rows)), 4) if rows else 0.0,
        }
    )
    export_summary_path = _car_number_text_dataset_summary_path()
    if export_summary_path.exists():
        try:
            export_summary = json.loads(export_summary_path.read_text(encoding="utf-8"))
            summary_payload["latest_export"] = {
                "generated_at": export_summary.get("generated_at"),
                "accepted_rows": export_summary.get("accepted_rows"),
                "skipped_missing_text": export_summary.get("skipped_missing_text"),
                "text_sources": export_summary.get("text_sources") or {},
                "output_dir": export_summary.get("output_dir"),
                "bundles": export_summary.get("bundles") or {},
            }
        except json.JSONDecodeError:
            summary_payload["latest_export"] = None
    return summary_payload


@router.get("/car-number-labeling/items")
def list_car_number_labeling_items(
    q: str | None = Query(default=None, description="关键词搜索 / Search sample_id, source_file, suggestion, final_text"),
    review_status: str | None = Query(default=None, pattern=REVIEW_STATUS_PATTERN, description="复核状态 / pending|done|needs_check"),
    has_final_text: bool | None = Query(default=None, description="是否已有 final_text / Has reviewed text"),
    has_suggestion: bool | None = Query(default=None, description="是否有 OCR 建议 / Has OCR suggestion"),
    split_hint: str | None = Query(default=None, description="数据集切分 / train|validation"),
    limit: int = Query(default=80, ge=1, le=500, description="返回条数 / Max items"),
    offset: int = Query(default=0, ge=0, description="偏移量 / Offset"),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    rows = _load_car_number_labeling_rows()
    token = str(q or "").strip().lower()
    filtered = []
    for row in rows:
        item = _labeling_item_summary(row)
        if token:
            searchable = " ".join(
                [
                    item["sample_id"],
                    item["source_file"],
                    item["ocr_suggestion"],
                    item["final_text"],
                    item["notes"],
                ]
            ).lower()
            if token not in searchable:
                continue
        if review_status and item["review_status"] != review_status:
            continue
        if split_hint and item["split_hint"] != split_hint:
            continue
        if has_final_text is not None and item["has_final_text"] != has_final_text:
            continue
        if has_suggestion is not None and item["has_suggestion"] != has_suggestion:
            continue
        filtered.append(item)
    total = len(filtered)
    page = filtered[offset: offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": page,
    }


@router.get("/car-number-labeling/items/{sample_id}/crop")
def get_car_number_labeling_crop(
    sample_id: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    rows = _load_car_number_labeling_rows()
    matched = next((row for row in rows if str(row.get("sample_id") or "").strip() == sample_id), None)
    if not matched:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Labeling sample not found")
    crop_rel = str(matched.get("crop_file") or "").strip()
    crop_path = _car_number_labeling_dir() / crop_rel
    if not crop_path.exists() or not crop_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop file not found")
    return FileResponse(crop_path)


@router.post("/car-number-labeling/items/{sample_id}/review")
def update_car_number_labeling_review(
    sample_id: str,
    payload: CarNumberLabelingReviewRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    rows = _load_car_number_labeling_rows()
    matched_index = next((idx for idx, row in enumerate(rows) if str(row.get("sample_id") or "").strip() == sample_id), None)
    if matched_index is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Labeling sample not found")
    row = dict(rows[matched_index])
    row["final_text"] = str(payload.final_text or "").strip().upper()
    row["review_status"] = payload.review_status
    row["reviewer"] = str(payload.reviewer or "").strip()
    row["notes"] = str(payload.notes or "").strip()
    rows[matched_index] = row
    _rewrite_car_number_labeling_files(rows)
    return {
        "status": "ok",
        "item": _labeling_item_summary(row),
    }


@router.post("/car-number-labeling/export-text-dataset")
def export_car_number_text_dataset(
    payload: CarNumberTextDatasetExportRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    return _export_car_number_text_dataset(allow_suggestions=payload.allow_suggestions)


@router.post("/car-number-labeling/export-text-assets")
def export_car_number_text_assets(
    payload: CarNumberTextDatasetAssetImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    return _export_car_number_text_assets_internal(payload=payload, request=request, db=db, current_user=current_user)


@router.post("/car-number-labeling/export-text-training-job")
def export_car_number_text_training_job(
    payload: CarNumberTextTrainingJobCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    asset_result = _export_car_number_text_assets_internal(payload=payload, request=request, db=db, current_user=current_user)
    intended_model_code = str(payload.intended_model_code or "").strip() or "car_number_ocr"
    base_model = _resolve_default_base_model(
        db=db,
        current_user=current_user,
        intended_model_code=intended_model_code,
        base_model_id=payload.base_model_id,
    )
    worker_selector: dict[str, Any] = {}
    worker_code = _clean_optional(payload.worker_code)
    worker_host = _clean_optional(payload.worker_host)
    if worker_code:
        worker_selector["worker_codes"] = [worker_code]
    if worker_host:
        worker_selector["hosts"] = [worker_host]
    create_payload = TrainingJobCreateRequest(
        asset_ids=asset_result["prefill"]["train_asset_ids"],
        validation_asset_ids=asset_result["prefill"]["validation_asset_ids"],
        base_model_id=base_model.id if base_model else None,
        owner_tenant_id=base_model.owner_tenant_id if base_model else None,
        training_kind=payload.training_kind,
        target_model_code=intended_model_code,
        target_version=_clean_optional(payload.target_version) or _auto_target_version(intended_model_code),
        worker_selector=worker_selector,
        spec=_default_car_number_training_spec(payload.spec),
    )
    job = create_training_job(create_payload, request=request, db=db, current_user=current_user)
    return {
        **asset_result,
        "job": job,
        "resolved_base_model": _model_summary(base_model),
        "resolved_spec": create_payload.spec,
    }


@router.get("/jobs/{job_id}")
def get_training_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    reconcile_training_runtime_health(db)
    job = _get_training_job_or_404(db, job_id, current_user)
    return _serialize_job(db, job)


@router.post("/jobs/{job_id}/cancel")
def cancel_training_job(
    job_id: str,
    payload: TrainingJobActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    job = _get_training_job_or_404(db, job_id, current_user)
    if job.status in TRAINING_JOB_TERMINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Training job already terminal")

    previous_status = job.status
    note = _control_note(payload.note)
    existing_summary = job.output_summary if isinstance(job.output_summary, dict) else {}
    job.status = TRAINING_JOB_STATUS_CANCELLED
    job.finished_at = datetime.utcnow()
    job.error_message = note or "Cancelled by operator"
    job.output_summary = {
        **existing_summary,
        "last_control_action": "cancel",
        "cancelled_at": datetime.utcnow().isoformat(),
        "cancelled_by": current_user.username,
        "cancel_note": note,
        "previous_status": previous_status,
    }
    db.add(job)
    db.commit()

    record_audit(
        db,
        action=actions.TRAINING_JOB_CANCEL,
        resource_type="training_job",
        resource_id=job.id,
        detail={"job_code": job.job_code, "previous_status": previous_status, "note": note},
        request=request,
        actor=current_user,
    )
    return _serialize_job(db, job)


@router.post("/jobs/{job_id}/retry")
def retry_training_job(
    job_id: str,
    payload: TrainingJobActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    job = _get_training_job_or_404(db, job_id, current_user)
    if job.status not in {TRAINING_JOB_STATUS_FAILED, TRAINING_JOB_STATUS_CANCELLED}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only FAILED or CANCELLED jobs can be retried")
    _ensure_retryable(job, "retry")

    previous_status = job.status
    previous_error = job.error_message
    note = _control_note(payload.note)
    existing_summary = job.output_summary if isinstance(job.output_summary, dict) else {}
    job.status = TRAINING_JOB_STATUS_PENDING
    job.assigned_worker_code = None
    job.started_at = None
    job.finished_at = None
    job.error_message = None
    job.output_summary = {
        **existing_summary,
        "retry_count": int(existing_summary.get("retry_count") or 0) + 1,
        "last_control_action": "retry",
        "last_retry_at": datetime.utcnow().isoformat(),
        "last_retry_by": current_user.username,
        "last_retry_note": note,
        "last_terminal_status": previous_status,
        "last_terminal_error": previous_error,
        "alert_level": None,
        "alert_reason": None,
        "recommended_action": None,
    }
    db.add(job)
    db.commit()

    record_audit(
        db,
        action=actions.TRAINING_JOB_RETRY,
        resource_type="training_job",
        resource_id=job.id,
        detail={"job_code": job.job_code, "previous_status": previous_status, "note": note},
        request=request,
        actor=current_user,
    )
    return _serialize_job(db, job)


@router.post("/jobs/{job_id}/reassign")
def reassign_training_job(
    job_id: str,
    payload: TrainingJobReassignRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    job = _get_training_job_or_404(db, job_id, current_user)
    if job.status == TRAINING_JOB_STATUS_RUNNING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="RUNNING job cannot be reassigned directly, cancel it first")
    if job.status == TRAINING_JOB_STATUS_SUCCEEDED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SUCCEEDED job cannot be reassigned")
    if job.status in TRAINING_JOB_TERMINAL_STATUSES:
        _ensure_retryable(job, "reassign")

    target_worker, target_worker_code, target_worker_host = _resolve_target_worker(db, payload.worker_code, payload.worker_host)
    note = _control_note(payload.note)
    previous_status = job.status
    existing_summary = job.output_summary if isinstance(job.output_summary, dict) else {}
    worker_selector = dict(job.worker_selector or {})
    if target_worker_code:
        worker_selector["worker_codes"] = [target_worker_code]
    elif target_worker and target_worker.worker_code:
        worker_selector["worker_codes"] = [target_worker.worker_code]
    if target_worker_host:
        worker_selector["hosts"] = [target_worker_host]
        worker_selector["host"] = target_worker_host

    job.worker_selector = worker_selector
    job.assigned_worker_code = None
    job.started_at = None
    job.finished_at = None
    job.error_message = None
    job.status = TRAINING_JOB_STATUS_PENDING
    job.output_summary = {
        **existing_summary,
        "reassign_count": int(existing_summary.get("reassign_count") or 0) + 1,
        "last_control_action": "reassign",
        "last_reassign_at": datetime.utcnow().isoformat(),
        "last_reassign_by": current_user.username,
        "last_reassign_note": note,
        "last_reassign_worker_code": target_worker_code or (target_worker.worker_code if target_worker else None),
        "last_reassign_worker_host": target_worker_host,
        "previous_status": previous_status,
        "alert_level": None,
        "alert_reason": None,
        "recommended_action": None,
    }
    db.add(job)
    db.commit()

    record_audit(
        db,
        action=actions.TRAINING_JOB_REASSIGN,
        resource_type="training_job",
        resource_id=job.id,
        detail={
            "job_code": job.job_code,
            "previous_status": previous_status,
            "worker_code": target_worker_code or (target_worker.worker_code if target_worker else None),
            "worker_host": target_worker_host,
            "note": note,
        },
        request=request,
        actor=current_user,
    )
    return _serialize_job(db, job)


@router.post("/workers/register")
def register_training_worker(
    payload: TrainingWorkerRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_WORKER_ADMIN_ROLES)),
):
    worker = db.query(TrainingWorker).filter(TrainingWorker.worker_code == payload.worker_code.strip()).first()
    raw_token = f"trainwk_{secrets.token_urlsafe(24)}"
    now = datetime.utcnow()

    if not worker:
        worker = TrainingWorker(
            id=str(uuid.uuid4()),
            worker_code=payload.worker_code.strip(),
            name=payload.name.strip(),
            status=payload.status,
            auth_token_hash=hash_password(raw_token),
            host=payload.host,
            labels=payload.labels,
            resources=payload.resources,
            created_by=current_user.id,
            last_seen_at=None,
        )
        db.add(worker)
    else:
        worker.name = payload.name.strip()
        worker.status = payload.status
        worker.host = payload.host
        worker.labels = payload.labels
        worker.resources = payload.resources
        worker.auth_token_hash = hash_password(raw_token)
        worker.last_seen_at = worker.last_seen_at or now
        db.add(worker)

    db.commit()

    record_audit(
        db,
        action=actions.TRAINING_WORKER_REGISTER,
        resource_type="training_worker",
        resource_id=worker.id,
        detail={"worker_code": worker.worker_code, "host": worker.host, "labels": worker.labels, "resources": worker.resources},
        request=request,
        actor=current_user,
    )
    response = _serialize_worker(db, worker)
    response["bootstrap_token"] = raw_token
    return response


@router.get("/workers")
def list_training_workers(
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_WORKER_READ_ROLES, *TRAINING_WORKER_ADMIN_ROLES)),
):
    reconcile_training_runtime_health(db)
    rows = db.query(TrainingWorker).order_by(TrainingWorker.created_at.desc()).all()
    return [_serialize_worker(db, row) for row in rows]


@router.post("/runtime/reconcile")
def reconcile_training_runtime(
    payload: TrainingRuntimeReconcileRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_WORKER_ADMIN_ROLES)),
):
    summary = reconcile_training_runtime_health(
        db,
        request=request,
        worker_stale_seconds=payload.worker_stale_seconds,
        dispatch_timeout_seconds=payload.dispatch_timeout_seconds,
        running_timeout_seconds=payload.running_timeout_seconds,
    )
    summary["requested_by"] = current_user.username
    summary["note"] = _control_note(payload.note)
    return summary


@router.post("/workers/heartbeat")
def training_worker_heartbeat(
    payload: TrainingWorkerHeartbeatRequest,
    request: Request,
    db: Session = Depends(get_db),
    worker_ctx: TrainingWorkerContext = Depends(get_training_worker),
):
    worker = db.query(TrainingWorker).filter(TrainingWorker.id == worker_ctx.id).first()
    if not worker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training worker not found")

    worker.host = payload.host or worker.host
    worker.status = payload.status
    worker.labels = payload.labels or worker.labels
    worker.resources = payload.resources or worker.resources
    worker.last_seen_at = datetime.utcnow()
    db.add(worker)
    db.commit()

    record_audit(
        db,
        action=actions.TRAINING_WORKER_HEARTBEAT,
        resource_type="training_worker",
        resource_id=worker.id,
        detail={"worker_code": worker.worker_code, "status": worker.status, "resources": worker.resources},
        request=request,
        actor_role="training-worker",
    )

    pending_jobs = db.query(TrainingJob).filter(TrainingJob.status == TRAINING_JOB_STATUS_PENDING).count()
    return {"worker_code": worker.worker_code, "status": worker.status, "pending_jobs": pending_jobs, "server_time": datetime.utcnow()}


@router.post("/workers/pull-jobs")
def training_worker_pull_jobs(
    payload: TrainingWorkerPullJobsRequest,
    request: Request,
    db: Session = Depends(get_db),
    worker_ctx: TrainingWorkerContext = Depends(get_training_worker),
):
    reconcile_training_runtime_health(db, request=request)
    worker = db.query(TrainingWorker).filter(TrainingWorker.id == worker_ctx.id).first()
    if not worker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training worker not found")
    if worker.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Training worker is not ACTIVE")

    worker.last_seen_at = datetime.utcnow()
    db.add(worker)

    jobs = []
    pending_rows = (
        db.query(TrainingJob)
        .filter(TrainingJob.status == TRAINING_JOB_STATUS_PENDING)
        .order_by(TrainingJob.created_at.asc())
        .all()
    )

    for row in pending_rows:
        if len(jobs) >= payload.limit:
            break
        if not _worker_matches_selector(row, worker):
            continue

        row.status = TRAINING_JOB_STATUS_DISPATCHED
        row.assigned_worker_code = worker.worker_code
        row.dispatch_count += 1
        existing_summary = row.output_summary if isinstance(row.output_summary, dict) else {}
        row.output_summary = {
            **existing_summary,
            "last_dispatched_at": datetime.utcnow().isoformat(),
            "last_dispatched_worker_code": worker.worker_code,
            "alert_level": None,
            "alert_reason": None,
            "recommended_action": None,
        }
        worker.last_job_at = datetime.utcnow()
        db.add(row)
        db.add(worker)

        assets = _get_assets_or_400(db, row.asset_ids or [])
        validations = _get_assets_or_400(db, row.validation_asset_ids or []) if row.validation_asset_ids else []
        base_model = db.query(ModelRecord).filter(ModelRecord.id == row.base_model_id).first() if row.base_model_id else None

        jobs.append(
            {
                **_serialize_job(db, row),
                "assets": [_asset_summary(asset) for asset in assets],
                "validation_assets": [_asset_summary(asset) for asset in validations],
                "base_model": _model_summary(base_model),
            }
        )

        record_audit(
            db,
            action=actions.TRAINING_JOB_ASSIGN,
            resource_type="training_job",
            resource_id=row.id,
            detail={"job_code": row.job_code, "assigned_worker_code": worker.worker_code},
            request=request,
            actor_role="training-worker",
        )

    db.commit()
    return {"worker_code": worker.worker_code, "jobs": jobs}


@router.get("/workers/job-control")
def training_worker_job_control(
    job_id: str = Query(..., description="训练作业ID / Training job ID"),
    db: Session = Depends(get_db),
    worker_ctx: TrainingWorkerContext = Depends(get_training_worker),
):
    reconcile_training_runtime_health(db)
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training job not found")

    reason = None
    should_stop = False
    if job.status in TRAINING_JOB_TERMINAL_STATUSES:
        should_stop = True
        reason = f"terminal:{job.status.lower()}"
    elif not job.assigned_worker_code:
        should_stop = True
        reason = "unassigned"
    elif job.assigned_worker_code != worker_ctx.code:
        should_stop = True
        reason = "reassigned"

    return {
        "job_id": job.id,
        "job_code": job.job_code,
        "status": job.status,
        "assigned_worker_code": job.assigned_worker_code,
        "should_stop": should_stop,
        "reason": reason,
        "output_summary": job.output_summary if isinstance(job.output_summary, dict) else {},
    }


@router.get("/workers/pull-asset")
def training_worker_pull_asset(
    request: Request,
    job_id: str = Query(..., description="训练作业ID / Training job ID"),
    asset_id: str = Query(..., description="资产ID / Asset ID included in the training job"),
    db: Session = Depends(get_db),
    worker_ctx: TrainingWorkerContext = Depends(get_training_worker),
):
    job = _get_worker_job_or_403(db, worker_ctx.code, job_id)
    allowed_asset_ids = set(job.asset_ids or []) | set(job.validation_asset_ids or [])
    if asset_id not in allowed_asset_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Asset not part of training job")

    asset = db.query(DataAsset).filter(DataAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if not os.path.exists(asset.storage_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file missing")

    with open(asset.storage_uri, "rb") as f:
        file_bytes = f.read()

    record_audit(
        db,
        action=actions.TRAINING_ASSET_PULL,
        resource_type="training_job",
        resource_id=job.id,
        detail={"job_code": job.job_code, "worker_code": worker_ctx.code, "asset_id": asset.id},
        request=request,
        actor_role="training-worker",
    )

    return {
        "job_id": job.id,
        "job_code": job.job_code,
        "asset": {
            "id": asset.id,
            "file_name": asset.file_name,
            "asset_type": asset.asset_type,
            "sensitivity_level": asset.sensitivity_level,
            "checksum": asset.checksum,
            "meta": asset.meta if isinstance(asset.meta, dict) else {},
            "purpose": "validation" if asset.id in set(job.validation_asset_ids or []) else "training",
        },
        "file_b64": base64.b64encode(file_bytes).decode("utf-8"),
    }


@router.post("/workers/pull-base-model")
def training_worker_pull_base_model(
    payload: TrainingWorkerPullBaseModelRequest,
    request: Request,
    db: Session = Depends(get_db),
    worker_ctx: TrainingWorkerContext = Depends(get_training_worker),
):
    job = _get_worker_job_or_403(db, worker_ctx.code, payload.job_id)
    if not job.base_model_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training job has no base model")

    model = db.query(ModelRecord).filter(ModelRecord.id == job.base_model_id).first()
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Base model not found")
    if not (os.path.exists(model.manifest_uri) and os.path.exists(model.encrypted_uri) and os.path.exists(model.signature_uri)):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Base model artifacts missing")

    blobs = load_model_blobs(model.manifest_uri, model.encrypted_uri, model.signature_uri)

    record_audit(
        db,
        action=actions.TRAINING_MODEL_PULL,
        resource_type="training_job",
        resource_id=job.id,
        detail={"job_code": job.job_code, "worker_code": worker_ctx.code, "base_model_id": model.id},
        request=request,
        actor_role="training-worker",
    )

    return {
        "job_id": job.id,
        "job_code": job.job_code,
        "base_model": {
            **_model_summary(model),
            "manifest_b64": blobs["manifest_b64"],
            "model_enc_b64": blobs["model_enc_b64"],
            "signature_b64": blobs["signature_b64"],
        },
    }


@router.post("/workers/upload-candidate")
def training_worker_upload_candidate(
    request: Request,
    job_id: str = Form(..., description="训练作业ID / Training job ID"),
    package: UploadFile = File(..., description="候选模型包ZIP / Candidate model package zip"),
    training_round: str = Form(default="", description="训练轮次 / Training round label"),
    dataset_label: str = Form(default="", description="数据批次标签 / Dataset label"),
    training_summary: str = Form(default="", description="训练摘要 / Training summary"),
    model_type: str = Form(default=MODEL_TYPE_EXPERT, description="模型类型 / Model type: router|expert"),
    runtime: str = Form(default="", description="运行时类型 / Runtime type"),
    plugin_name: str = Form(default="", description="插件名称 / Plugin name for edge runtime"),
    inputs_json: str = Form(default="", description="输入协议JSON / Input schema JSON object"),
    outputs_json: str = Form(default="", description="输出协议JSON / Output schema JSON object"),
    gpu_mem_mb: str = Form(default="", description="显存需求MB / Optional GPU memory requirement in MB"),
    latency_ms: str = Form(default="", description="时延指标ms / Optional latency metric in milliseconds"),
    db: Session = Depends(get_db),
    worker_ctx: TrainingWorkerContext = Depends(get_training_worker),
):
    job = _get_worker_job_or_403(db, worker_ctx.code, job_id)
    if job.candidate_model_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Training job already has a candidate model")
    if not package.filename.endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .zip model package is allowed")

    package_bytes = package.file.read()
    settings = get_settings()
    try:
        parsed = parse_and_validate_model_package(package_bytes, settings.model_signing_public_key)
    except ModelPackageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # 关键校验：候选模型包的 model_id/version 必须与训练作业目标一致，防止错包入库。
    # Candidate manifest must match training target to prevent wrong-package ingestion.
    if parsed.manifest.get("model_id") != job.target_model_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Candidate package model_id does not match training job target_model_code")
    if parsed.manifest.get("version") != job.target_version:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Candidate package version does not match training job target_version")

    existing = (
        db.query(ModelRecord)
        .filter(ModelRecord.model_code == parsed.manifest["model_id"], ModelRecord.version == parsed.manifest["version"])
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Model code+version already exists")

    normalized_model_type = _clean_optional(model_type) or parsed.manifest.get("model_type") or MODEL_TYPE_EXPERT
    if normalized_model_type not in {MODEL_TYPE_ROUTER, MODEL_TYPE_EXPERT}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid model_type")

    model_id = str(uuid.uuid4())
    os.makedirs(settings.model_repo_path, exist_ok=True)
    uris = persist_model_package(settings.model_repo_path, model_id, parsed)

    base_model = db.query(ModelRecord).filter(ModelRecord.id == job.base_model_id).first() if job.base_model_id else None
    candidate = ModelRecord(
        id=model_id,
        model_code=parsed.manifest["model_id"],
        version=parsed.manifest["version"],
        model_hash=parsed.model_hash,
        model_type=normalized_model_type,
        runtime=_clean_optional(runtime) or parsed.manifest.get("runtime") or parsed.manifest.get("model_format") or "python",
        inputs=normalize_model_inputs(_parse_json_or_none(inputs_json) or parsed.manifest.get("inputs") or parsed.manifest.get("input_schema")),
        outputs=normalize_model_outputs(normalized_model_type, _parse_json_or_none(outputs_json) or parsed.manifest.get("outputs") or parsed.manifest.get("output_schema")),
        plugin_name=_clean_optional(plugin_name) or parsed.manifest.get("plugin_name") or parsed.manifest.get("task_type") or parsed.manifest["model_id"],
        gpu_mem_mb=int(gpu_mem_mb) if str(gpu_mem_mb).strip() else None,
        latency_ms=int(latency_ms) if str(latency_ms).strip() else None,
        encrypted_uri=uris["encrypted_uri"],
        signature_uri=uris["signature_uri"],
        manifest_uri=uris["manifest_uri"],
        manifest=parsed.manifest,
        status=MODEL_STATUS_SUBMITTED,
        created_by=job.requested_by,
        owner_tenant_id=job.owner_tenant_id,
    )
    db.add(candidate)
    db.commit()

    platform_meta = _platform_meta_for_candidate(
        job,
        base_model,
        dataset_label=_clean_optional(dataset_label),
        training_round=_clean_optional(training_round),
        training_summary=_clean_optional(training_summary),
    )
    candidate.manifest = {
        **candidate.manifest,
        "model_type": candidate.model_type,
        "runtime": candidate.runtime,
        "plugin_name": candidate.plugin_name,
        "inputs": candidate.inputs,
        "outputs": candidate.outputs,
        "platform_meta": platform_meta,
    }
    existing_summary = job.output_summary if isinstance(job.output_summary, dict) else {}
    job.candidate_model_id = candidate.id
    job.output_summary = {
        **existing_summary,
        "candidate_model_id": candidate.id,
        "candidate_model_code": candidate.model_code,
        "candidate_model_version": candidate.version,
        "candidate_model_hash": candidate.model_hash,
    }
    db.add(candidate)
    db.add(job)
    db.commit()

    record_audit(
        db,
        action=actions.TRAINING_CANDIDATE_UPLOAD,
        resource_type="training_job",
        resource_id=job.id,
        detail={
            "job_code": job.job_code,
            "worker_code": worker_ctx.code,
            "candidate_model_id": candidate.id,
            "candidate_model_code": candidate.model_code,
            "candidate_model_version": candidate.version,
        },
        request=request,
        actor_role="training-worker",
    )

    return {
        "job_id": job.id,
        "job_code": job.job_code,
        "candidate_model": {
            **_model_summary(candidate),
            "status": candidate.status,
            "platform_meta": platform_meta,
        },
    }


@router.post("/workers/push-update")
def training_worker_push_update(
    payload: TrainingWorkerUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    worker_ctx: TrainingWorkerContext = Depends(get_training_worker),
):
    job = db.query(TrainingJob).filter(TrainingJob.id == payload.job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training job not found")
    if not job.assigned_worker_code:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Training job is not assigned to any worker")
    if job.assigned_worker_code != worker_ctx.code:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Training job assigned to a different worker")
    if job.status in TRAINING_JOB_TERMINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Training job already terminal")

    worker = db.query(TrainingWorker).filter(TrainingWorker.id == worker_ctx.id).first()
    if worker:
        worker.last_seen_at = datetime.utcnow()
        db.add(worker)

    existing_output_summary = job.output_summary if isinstance(job.output_summary, dict) else {}
    job.status = payload.status
    next_summary = {**existing_output_summary, **payload.output_summary}
    if payload.status in {TRAINING_JOB_STATUS_RUNNING, TRAINING_JOB_STATUS_SUCCEEDED}:
        next_summary["alert_level"] = payload.output_summary.get("alert_level")
        next_summary["alert_reason"] = payload.output_summary.get("alert_reason")
        next_summary["recommended_action"] = payload.output_summary.get("recommended_action")
    job.output_summary = next_summary
    job.error_message = payload.error_message
    job.assigned_worker_code = worker_ctx.code
    if payload.status == TRAINING_JOB_STATUS_RUNNING and not job.started_at:
        job.started_at = datetime.utcnow()
    if payload.status in TRAINING_JOB_TERMINAL_STATUSES:
        job.finished_at = datetime.utcnow()
    db.add(job)
    db.commit()

    record_audit(
        db,
        action=actions.TRAINING_JOB_UPDATE,
        resource_type="training_job",
        resource_id=job.id,
        detail={
            "job_code": job.job_code,
            "status": job.status,
            "worker_code": worker_ctx.code,
            "output_summary": payload.output_summary,
            "error_message": payload.error_message,
        },
        request=request,
        actor_role="training-worker",
    )
    return _serialize_job(db, job)
