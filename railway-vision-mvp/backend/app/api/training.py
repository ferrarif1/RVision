import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
import secrets
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
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
from app.core.ui_errors import raise_ui_error
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
from app.services.car_number_rule_service import ensure_valid_car_number_text
from app.services.car_number_rule_service import get_active_car_number_rule
from app.services.car_number_rule_service import validate_car_number_text
from app.services.data_hygiene_service import is_synthetic_training_job
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
def _detect_repo_root() -> Path:
    here = Path(__file__).resolve()
    preferred_markers = ("config", "demo_data")
    for candidate in here.parents:
        if all((candidate / marker).exists() for marker in preferred_markers):
            return candidate
    for candidate in (Path("/app"), here.parents[2] if len(here.parents) > 2 else here.parent):
        if all((candidate / marker).exists() for marker in preferred_markers):
            return candidate
    return here.parents[2] if len(here.parents) > 2 else here.parent


REPO_ROOT = _detect_repo_root()
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


class TrainingWorkerCleanupRequest(BaseModel):
    stale_hours: int = Field(default=24, ge=1, le=24 * 365, description="清理阈值（小时） / Delete only workers stale for at least this many hours")
    worker_codes: list[str] = Field(default_factory=list, description="可选，精确指定要清理的 worker_code 列表 / Optional explicit worker codes to prune")
    dry_run: bool = Field(default=False, description="仅预览，不执行删除 / Preview only")
    limit: int = Field(default=200, ge=1, le=1000, description="单次最多处理多少条 / Max rows per cleanup")
    note: str | None = Field(default=None, description="清理说明 / Optional operator note")


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


class InspectionOcrLabelingReviewRequest(BaseModel):
    final_text: str | None = Field(default=None, description="人工确认后的文本 / Reviewed OCR text")
    review_status: str = Field(default="pending", pattern=REVIEW_STATUS_PATTERN, description="复核状态 / pending|done|needs_check")
    reviewer: str | None = Field(default=None, description="复核人 / Reviewer")
    notes: str | None = Field(default=None, description="备注 / Notes")


class InspectionOcrDatasetExportRequest(BaseModel):
    allow_suggestions: bool = Field(default=False, description="当 final_text 为空时，是否允许使用 ocr_suggestion / Allow OCR suggestion fallback")
    allow_proxy_seeded: bool = Field(default=False, description="是否允许带代理回灌真值继续导出 / Allow proxy-seeded truths for cold-start training")


class InspectionOcrDatasetAssetImportRequest(BaseModel):
    allow_suggestions: bool = Field(default=False, description="当 final_text 为空时，是否允许使用 ocr_suggestion / Allow OCR suggestion fallback")
    allow_proxy_seeded: bool = Field(default=False, description="是否允许带代理回灌真值继续导出 / Allow proxy-seeded truths for cold-start training")
    use_case: str = Field(default="", description="业务场景；为空时按任务类型自动生成 / Optional use case")
    intended_model_code: str = Field(default="", description="目标模型编码；为空时默认使用 task_type / Optional intended model code")
    sensitivity_level: str = Field(default="L2", description="敏感级别 / L1|L2|L3")


class InspectionOcrTrainingJobCreateRequest(InspectionOcrDatasetAssetImportRequest):
    training_kind: str = Field(default="finetune", pattern=TRAINING_KIND_PATTERN, description="训练类型 / train|finetune|evaluate")
    target_version: str | None = Field(default=None, description="目标版本；为空时自动生成 / Optional explicit target version")
    base_model_id: str | None = Field(default=None, description="基础模型 ID；为空时自动选择同编码模型 / Optional base model ID")
    worker_code: str | None = Field(default=None, description="指定训练机编码 / Optional worker code")
    worker_host: str | None = Field(default=None, description="指定训练机 host / Optional worker host")
    spec: dict[str, Any] = Field(default_factory=dict, description="训练参数覆盖 / Optional spec overrides")


class InspectionOcrBulkImportSummary(BaseModel):
    total_rows: int = Field(default=0, description="CSV 总行数（不含表头） / Total CSV rows")
    matched_rows: int = Field(default=0, description="命中 sample_id 的行数 / Rows matched to existing samples")
    updated_rows: int = Field(default=0, description="成功更新条数 / Updated rows")
    would_update_rows: int = Field(default=0, description="预检查模式下将会更新的条数 / Rows that would be updated in preview mode")
    skipped_rows: int = Field(default=0, description="跳过条数 / Skipped rows")
    missing_sample_ids: list[str] = Field(default_factory=list, description="未命中的 sample_id / Missing sample ids")
    unchanged_sample_ids: list[str] = Field(default_factory=list, description="内容未变化的 sample_id / Unchanged sample ids")


class InspectionOcrBulkAcceptHighQualityRequest(BaseModel):
    sample_ids: list[str] = Field(default_factory=list, description="可选，仅处理这些样本 / Optional explicit sample ids")
    limit: int = Field(default=20, ge=1, le=200, description="本次最多处理多少条 / Max rows to process")
    reviewer: str | None = Field(default=None, description="批量确认人 / Reviewer")
    notes: str | None = Field(default=None, description="批量确认备注 / Notes")


class InspectionOcrBulkAcceptHighQualitySummary(BaseModel):
    total_candidates: int = Field(default=0, description="当前高质量建议候选总数 / Total high-quality candidates")
    selected_rows: int = Field(default=0, description="本次命中的样本数 / Rows selected for this operation")
    updated_rows: int = Field(default=0, description="正式执行时已更新的条数 / Updated rows")
    would_update_rows: int = Field(default=0, description="预检查模式下将会更新的条数 / Rows that would be updated in preview mode")
    skipped_rows: int = Field(default=0, description="跳过条数 / Skipped rows")
    unmatched_sample_ids: list[str] = Field(default_factory=list, description="不在高质量候选中的 sample_id / Sample ids not eligible")
    changed_sample_ids: list[str] = Field(default_factory=list, description="将被更新或已更新的 sample_id / Changed sample ids")
    unchanged_sample_ids: list[str] = Field(default_factory=list, description="内容未变化的 sample_id / Unchanged sample ids")


class InspectionOcrBulkConfirmProxyRequest(BaseModel):
    sample_ids: list[str] = Field(default_factory=list, description="可选，仅处理这些代理样本 / Optional explicit proxy sample ids")
    limit: int = Field(default=20, ge=1, le=200, description="本次最多处理多少条 / Max rows to process")
    reviewer: str | None = Field(default=None, description="确认人 / Reviewer")
    notes: str | None = Field(default=None, description="确认备注 / Notes")


class InspectionOcrBulkConfirmProxySummary(BaseModel):
    total_candidates: int = Field(default=0, description="当前代理回灌候选总数 / Total proxy-seeded candidates")
    selected_rows: int = Field(default=0, description="本次命中的样本数 / Rows selected for this operation")
    updated_rows: int = Field(default=0, description="正式执行时已更新的条数 / Updated rows")
    would_update_rows: int = Field(default=0, description="预检查模式下将会更新的条数 / Rows that would be updated in preview mode")
    skipped_rows: int = Field(default=0, description="跳过条数 / Skipped rows")
    unmatched_sample_ids: list[str] = Field(default_factory=list, description="不在代理候选中的 sample_id / Sample ids not eligible")
    changed_sample_ids: list[str] = Field(default_factory=list, description="将被更新或已更新的 sample_id / Changed sample ids")
    unchanged_sample_ids: list[str] = Field(default_factory=list, description="内容未变化的 sample_id / Unchanged sample ids")


class InspectionOcrBulkResolveBlockerRequest(BaseModel):
    sample_ids: list[str] = Field(default_factory=list, description="可选，仅处理这些阻断样本 / Optional explicit blocker sample ids")
    limit: int = Field(default=20, ge=1, le=200, description="本次最多处理多少条 / Max rows to process")
    reviewer: str | None = Field(default=None, description="确认人 / Reviewer")
    notes: str | None = Field(default=None, description="确认备注 / Notes")


class InspectionOcrBulkResolveBlockerSummary(BaseModel):
    total_blockers: int = Field(default=0, description="当前训练阻断样本总数 / Total readiness blocker rows")
    selected_rows: int = Field(default=0, description="本次命中的样本数 / Rows selected for this operation")
    updated_rows: int = Field(default=0, description="正式执行时已更新的条数 / Updated rows")
    would_update_rows: int = Field(default=0, description="预检查模式下将会更新的条数 / Rows that would be updated in preview mode")
    skipped_rows: int = Field(default=0, description="跳过条数 / Skipped rows")
    unmatched_sample_ids: list[str] = Field(default_factory=list, description="不在当前阻断样本中的 sample_id / Sample ids not eligible")
    changed_sample_ids: list[str] = Field(default_factory=list, description="将被更新或已更新的 sample_id / Changed sample ids")
    unchanged_sample_ids: list[str] = Field(default_factory=list, description="内容未变化的 sample_id / Unchanged sample ids")
    resolved_reasons: list[str] = Field(default_factory=list, description="本次涉及的阻断原因 / Resolved blocker reasons")


class InspectionStateLabelingReviewRequest(BaseModel):
    label_value: str | None = Field(default=None, description="人工确认后的状态/缺陷标签 / Reviewed state label")
    review_status: str = Field(default="pending", pattern=REVIEW_STATUS_PATTERN, description="复核状态 / pending|done|needs_check")
    reviewer: str | None = Field(default=None, description="复核人 / Reviewer")
    notes: str | None = Field(default=None, description="备注 / Notes")


class InspectionStateDatasetAssetImportRequest(BaseModel):
    use_case: str = Field(default="", description="业务场景；为空时按任务类型自动生成 / Optional use case")
    intended_model_code: str = Field(default="", description="目标模型编码；为空时默认使用 task_type / Optional intended model code")
    sensitivity_level: str = Field(default="L2", description="敏感级别 / L1|L2|L3")


class InspectionStateTrainingJobCreateRequest(InspectionStateDatasetAssetImportRequest):
    training_kind: str = Field(default="train", pattern=TRAINING_KIND_PATTERN, description="训练类型 / train|finetune|evaluate")
    target_version: str | None = Field(default=None, description="目标版本；为空时自动生成 / Optional explicit target version")
    base_model_id: str | None = Field(default=None, description="基础模型 ID；为空时自动选择同编码模型 / Optional base model ID")
    worker_code: str | None = Field(default=None, description="指定训练机编码 / Optional worker code")
    worker_host: str | None = Field(default=None, description="指定训练机 host / Optional worker host")
    spec: dict[str, Any] = Field(default_factory=dict, description="训练参数覆盖 / Optional spec overrides")


class InspectionStateImportAssetsRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, description="待导入的图片资产编号 / Image asset ids to import")
    note: str | None = Field(default=None, description="导入说明 / Optional operator note")


class InspectionStateBulkImportSummary(BaseModel):
    total_rows: int = Field(default=0, description="CSV 总行数（不含表头） / Total CSV rows")
    matched_rows: int = Field(default=0, description="命中 sample_id 的行数 / Rows matched to existing samples")
    updated_rows: int = Field(default=0, description="成功更新条数 / Updated rows")
    would_update_rows: int = Field(default=0, description="预检查模式下将会更新的条数 / Rows that would be updated in preview mode")
    skipped_rows: int = Field(default=0, description="跳过条数 / Skipped rows")
    missing_sample_ids: list[str] = Field(default_factory=list, description="未命中的 sample_id / Missing sample ids")
    unchanged_sample_ids: list[str] = Field(default_factory=list, description="内容未变化的 sample_id / Unchanged sample ids")


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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "training_job_not_found",
            "训练作业不存在，或当前账号看不到这条作业。",
            next_step="请回到训练中心刷新列表，再重新选择需要查看的作业。",
        )
    return job


def _get_assets_or_400(db: Session, asset_ids: list[str]) -> list[DataAsset]:
    rows = db.query(DataAsset).filter(DataAsset.id.in_(asset_ids)).all()
    found = {row.id: row for row in rows}
    missing = [asset_id for asset_id in asset_ids if asset_id not in found]
    if missing:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_asset_not_found",
            "训练或验证资源里有记录不存在，当前作业不能继续创建。",
            next_step="请刷新资源列表，确认 asset_id 是否仍有效，再重新提交训练作业。",
            raw_detail={"missing_asset_id": missing[0]},
        )
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


def _inspection_dataset_blueprints_path() -> Path:
    return REPO_ROOT / "config" / "railcar_inspection_dataset_blueprints.json"


def _load_inspection_dataset_blueprints() -> dict[str, Any]:
    path = _inspection_dataset_blueprints_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    tasks = payload.get("tasks") or {}
    return tasks if isinstance(tasks, dict) else {}


def _inspection_labeling_dir(task_type: str) -> Path:
    override = str(os.getenv("INSPECTION_LABELING_BASE_DIR") or "").strip()
    suffix = f"{task_type}_labeling"
    candidates = [Path(override) / suffix] if override else []
    candidates.extend(
        [
            REPO_ROOT / "demo_data" / "generated_datasets" / suffix,
            Path("/app/demo_data/generated_datasets") / suffix,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _inspection_labeling_manifest_path(task_type: str) -> Path:
    return _inspection_labeling_dir(task_type) / "manifest.csv"


def _inspection_labeling_jsonl_path(task_type: str) -> Path:
    return _inspection_labeling_dir(task_type) / "manifest.jsonl"


def _inspection_labeling_summary_path(task_type: str) -> Path:
    return _inspection_labeling_dir(task_type) / "summary.json"


def _inspection_dataset_output_dir(task_type: str) -> Path:
    override = str(os.getenv("INSPECTION_DATASET_BASE_DIR") or "").strip()
    suffix = f"{task_type}_dataset"
    candidates = [Path(override) / suffix] if override else []
    candidates.extend(
        [
            REPO_ROOT / "demo_data" / "generated_datasets" / suffix,
            Path("/app/demo_data/generated_datasets") / suffix,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_inspection_labeling_rows(task_type: str) -> list[dict[str, str]]:
    manifest_path = _inspection_labeling_manifest_path(task_type)
    if not manifest_path.exists():
        return []
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _resolve_image_path(row: dict[str, str], *, manifest_path: Path) -> Path | None:
    crop_rel = str(row.get("crop_file") or "").strip()
    if crop_rel:
        crop_path = (manifest_path.parent / crop_rel).resolve()
        if crop_path.exists() and crop_path.is_file():
            return crop_path
    source_rel = str(row.get("source_file") or "").strip()
    if source_rel:
        source_path = (manifest_path.parent / source_rel).resolve()
        if source_path.exists() and source_path.is_file():
            return source_path
        alt_path = (REPO_ROOT / source_rel).resolve()
        if alt_path.exists() and alt_path.is_file():
            return alt_path
    return None


def _get_inspection_blueprint_or_404(task_type: str) -> dict[str, Any]:
    blueprints = _load_inspection_dataset_blueprints()
    blueprint = blueprints.get(task_type)
    if not isinstance(blueprint, dict):
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_task_not_found",
            "巡检任务类型不存在，或当前工作区还没初始化。",
            next_step="请回到训练中心确认任务类型，或先生成对应的数据工作区模板。",
        )
    return blueprint


def _get_inspection_ocr_blueprint_or_404(task_type: str) -> dict[str, Any]:
    blueprint = _get_inspection_blueprint_or_404(task_type)
    if str(blueprint.get("dataset_kind") or "").strip() != "ocr_text":
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_task_not_ocr_text",
            "当前任务不是文字识别工作区，不能进入文字复核。",
            next_step="请改用定检标记识别或性能标记识别这类文字识别任务。",
        )
    return blueprint


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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_metadata_json_invalid",
            "填写的 JSON 元数据格式不正确。",
            next_step="请检查 JSON 语法，例如逗号、引号和大括号是否完整。",
            raw_detail=str(exc),
        )
    if not isinstance(parsed, dict):
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_metadata_json_object_required",
            "JSON 元数据必须是对象格式。",
            next_step="请使用 {\"key\": \"value\"} 这样的对象格式填写。",
        )
    return parsed


def _load_car_number_labeling_rows() -> list[dict[str, str]]:
    manifest_path = _car_number_labeling_manifest_path()
    if not manifest_path.exists():
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "labeling_manifest_not_found",
            "没有找到车号文本复核清单。",
            next_step="请先生成车号文本复核清单，或确认 demo_data 已正确准备。",
        )
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _rewrite_car_number_labeling_files(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "labeling_manifest_empty",
            "车号文本复核清单为空。",
            next_step="请先准备待复核样本，再继续保存或导出。",
        )
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


def _rewrite_inspection_labeling_files(task_type: str, rows: list[dict[str, str]]) -> None:
    blueprint = _get_inspection_blueprint_or_404(task_type)
    if not rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_labeling_manifest_empty",
            "巡检任务复核清单为空。",
            next_step="请先准备待复核样本，再继续保存或导出。",
        )
    manifest_path = _inspection_labeling_manifest_path(task_type)
    jsonl_path = _inspection_labeling_jsonl_path(task_type)
    summary_path = _inspection_labeling_summary_path(task_type)
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
    final_text_rows = 0
    suggestion_rows = 0
    high_quality_suggestion_rows = 0
    crop_ready_rows = 0
    split_counts: dict[str, int] = {}
    for row in rows:
        review_key = str(row.get("review_status") or "pending").strip() or "pending"
        review_status_counts[review_key] = review_status_counts.get(review_key, 0) + 1
        if str(row.get("final_text") or "").strip():
            final_text_rows += 1
        if str(row.get("ocr_suggestion") or "").strip():
            suggestion_rows += 1
            if float(row.get("ocr_suggestion_quality") or 0.0) >= 1.0:
                high_quality_suggestion_rows += 1
        if str(row.get("crop_file") or "").strip():
            crop_ready_rows += 1
        split_key = str(row.get("split_hint") or "").strip() or "unassigned"
        split_counts[split_key] = split_counts.get(split_key, 0) + 1
    summary.update(
        {
            "status": "ok",
            "generated_at": datetime.utcnow().isoformat(),
            "task_type": task_type,
            "task_label": str(blueprint.get("label") or task_type),
            "dataset_kind": str(blueprint.get("dataset_kind") or ""),
            "dataset_key_prefix": str(blueprint.get("dataset_key_prefix") or ""),
            "annotation_format": str(blueprint.get("annotation_format") or ""),
            "sample_target_min": int(blueprint.get("sample_target_min") or 0),
            "sample_target_recommended": int(blueprint.get("sample_target_recommended") or 0),
            "structured_fields": list(blueprint.get("structured_fields") or []),
            "capture_profile": blueprint.get("capture_profile") or {},
            "qa_targets": blueprint.get("qa_targets") or {},
            "review_status_values": list(blueprint.get("review_status_values") or []),
            "workspace_dir": _relative_repo_path(_inspection_labeling_dir(task_type)),
            "manifest_csv": _relative_repo_path(manifest_path),
            "manifest_jsonl": _relative_repo_path(jsonl_path),
            "capture_plan_csv": _relative_repo_path(_inspection_labeling_dir(task_type) / "capture_plan.csv"),
            "crops_dir": _relative_repo_path(_inspection_labeling_dir(task_type) / "crops"),
            "row_count": len(rows),
            "crop_ready_rows": crop_ready_rows,
            "suggestion_rows": suggestion_rows,
            "review_status_counts": review_status_counts,
            "final_text_rows": final_text_rows,
            "ready_rows": final_text_rows,
            "ready_ratio": round((final_text_rows / len(rows)), 4) if rows else 0.0,
            "split_counts": split_counts,
            "notes": list(blueprint.get("notes") or []),
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _labeling_item_summary(row: dict[str, str]) -> dict[str, Any]:
    final_text = str(row.get("final_text") or "").strip()
    suggestion = str(row.get("ocr_suggestion") or "").strip()
    final_validation = validate_car_number_text(final_text)
    suggestion_validation = validate_car_number_text(suggestion)
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
        "final_text_validation": final_validation,
        "ocr_suggestion_validation": suggestion_validation,
        "car_number_rule": get_active_car_number_rule(),
    }


def _inspection_ocr_labeling_item_summary(task_type: str, row: dict[str, str]) -> dict[str, Any]:
    blueprint = _get_inspection_ocr_blueprint_or_404(task_type)
    final_text = str(row.get("final_text") or "").strip().upper()
    suggestion = str(row.get("ocr_suggestion") or "").strip().upper()
    reviewer = str(row.get("reviewer") or "").strip()
    proxy_seeded = reviewer == "proxy_from_car_number_truth"
    if proxy_seeded:
        review_origin_label = "代理回灌"
    elif reviewer:
        review_origin_label = "人工复核"
    else:
        review_origin_label = "尚未确认"
    return {
        "sample_id": str(row.get("sample_id") or "").strip(),
        "task_type": task_type,
        "task_label": str(blueprint.get("label") or task_type),
        "split_hint": str(row.get("split_hint") or "").strip(),
        "source_file": str(row.get("source_file") or "").strip(),
        "crop_file": str(row.get("crop_file") or "").strip(),
        "label_class": str(row.get("label_class") or "").strip(),
        "review_status": str(row.get("review_status") or "pending").strip() or "pending",
        "reviewer": reviewer,
        "proxy_seeded": proxy_seeded,
        "review_origin_label": review_origin_label,
        "notes": str(row.get("notes") or "").strip(),
        "final_text": final_text,
        "ocr_suggestion": suggestion,
        "ocr_suggestion_confidence": float(row.get("ocr_suggestion_confidence") or 0) if str(row.get("ocr_suggestion_confidence") or "").strip() else None,
        "ocr_suggestion_quality": float(row.get("ocr_suggestion_quality") or 0) if str(row.get("ocr_suggestion_quality") or "").strip() else None,
        "ocr_suggestion_engine": str(row.get("ocr_suggestion_engine") or "").strip(),
        "has_final_text": bool(final_text),
        "has_suggestion": bool(suggestion),
        "bbox": [
            int(row.get("bbox_x1") or 0),
            int(row.get("bbox_y1") or 0),
            int(row.get("bbox_x2") or 0),
            int(row.get("bbox_y2") or 0),
        ],
    }


def _inspection_suggestion_priority_label(item: dict[str, Any]) -> str:
    quality = item.get("ocr_suggestion_quality")
    if quality is None:
        return "无建议"
    if float(quality) >= 1.0:
        return "高质量建议"
    if float(quality) >= 0.8:
        return "中质量建议"
    return "低质量建议"


def _inspection_item_sort_key(item: dict[str, Any]) -> tuple:
    review_status = str(item.get("review_status") or "")
    proxy_seeded = bool(item.get("proxy_seeded"))
    has_final = bool(item.get("has_final_text"))
    quality = float(item.get("ocr_suggestion_quality") or 0.0)
    has_suggestion = bool(item.get("has_suggestion"))
    split = str(item.get("split_hint") or "")
    status_rank = {"needs_check": 0, "pending": 1, "done": 2}.get(review_status, 3)
    split_rank = {"validation": 0, "train": 1}.get(split, 2)
    return (
        status_rank,
        0 if proxy_seeded else 1,
        0 if (not has_final and has_suggestion) else 1,
        -quality,
        split_rank,
        str(item.get("sample_id") or ""),
    )


def _resolve_car_number_text(row: dict[str, str], *, allow_suggestions: bool) -> tuple[str, str]:
    final_text = str(row.get("final_text") or "").strip().upper()
    if final_text and validate_car_number_text(final_text)["valid"]:
        return validate_car_number_text(final_text)["normalized_text"], "final_text"
    if allow_suggestions:
        suggestion = str(row.get("ocr_suggestion") or "").strip().upper()
        if suggestion and validate_car_number_text(suggestion)["valid"]:
            return validate_car_number_text(suggestion)["normalized_text"], "ocr_suggestion"
    return "", ""


def _resolve_inspection_ocr_text(row: dict[str, str], *, allow_suggestions: bool) -> tuple[str, str]:
    final_text = str(row.get("final_text") or "").strip().upper()
    if final_text:
        return final_text, "final_text"
    if allow_suggestions:
        suggestion = str(row.get("ocr_suggestion") or "").strip().upper()
        if suggestion:
            return suggestion, "ocr_suggestion"
    return "", ""


def _inspection_crop_quality_score(task_type: str, row: dict[str, str]) -> float:
    crop_rel = str(row.get("crop_file") or "").strip()
    if not crop_rel:
        return 0.0
    crop_path = _inspection_labeling_dir(task_type) / crop_rel
    if not crop_path.exists() or not crop_path.is_file():
        return 0.0
    width = max(int(row.get("bbox_x2") or 0) - int(row.get("bbox_x1") or 0), 0)
    height = max(int(row.get("bbox_y2") or 0) - int(row.get("bbox_y1") or 0), 0)
    area_score = min((width * height) / 100000.0, 8.0)
    width_score = min(width / 220.0, 2.5)
    height_score = min(height / 90.0, 2.0)
    split_bonus = 0.15 if str(row.get("split_hint") or "").strip() == "validation" else 0.0
    return round(area_score + width_score + height_score + split_bonus, 4)


def _inspection_starter_samples(task_type: str, rows: list[dict[str, str]], *, limit: int = 8) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        if str(row.get("final_text") or "").strip():
            continue
        if str(row.get("review_status") or "").strip() == "done":
            continue
        score = _inspection_crop_quality_score(task_type, row)
        if score <= 0:
            continue
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    starters = []
    for score, row in ranked[:limit]:
        starters.append(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "split_hint": str(row.get("split_hint") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "quality_score": score,
                "review_status": str(row.get("review_status") or "pending").strip() or "pending",
            }
        )
    return starters


def _inspection_proxy_replacement_samples(task_type: str, rows: list[dict[str, str]], *, limit: int = 8) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        reviewer = str(row.get("reviewer") or "").strip()
        if reviewer != "proxy_from_car_number_truth":
            continue
        if not str(row.get("final_text") or "").strip():
            continue
        score = _inspection_crop_quality_score(task_type, row)
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    samples = []
    for score, row in ranked[:limit]:
        samples.append(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "split_hint": str(row.get("split_hint") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "quality_score": score,
                "review_status": str(row.get("review_status") or "pending").strip() or "pending",
                "review_origin_label": "代理回灌",
            }
        )
    return samples


def _inspection_proxy_seeded_rows(task_type: str) -> list[dict[str, str]]:
    rows = _load_inspection_labeling_rows(task_type)
    return [
        row
        for row in rows
        if str(row.get("reviewer") or "").strip() == "proxy_from_car_number_truth"
        and str(row.get("final_text") or "").strip()
    ]


def _inspection_readiness_blocker_rows(task_type: str) -> list[dict[str, str]]:
    rows = _load_inspection_labeling_rows(task_type)
    readiness = _inspection_ocr_training_readiness(task_type, rows)
    if str(readiness.get("status") or "").strip() == "ready":
        return []
    return _inspection_proxy_seeded_rows(task_type)


def _inspection_readiness_blocker_reason(row: dict[str, str]) -> str:
    reviewer = str(row.get("reviewer") or "").strip()
    if reviewer == "proxy_from_car_number_truth":
        return "proxy_seeded_truth"
    return "unknown"


def _inspection_high_quality_suggestion_candidate_rows(task_type: str) -> list[dict[str, str]]:
    rows = _load_inspection_labeling_rows(task_type)
    candidates: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        if str(row.get("final_text") or "").strip():
            continue
        suggestion = str(row.get("ocr_suggestion") or "").strip()
        if not suggestion:
            continue
        quality = float(row.get("ocr_suggestion_quality") or 0.0)
        if quality < 1.0:
            continue
        score = quality * 100.0 + _inspection_crop_quality_score(task_type, row)
        candidates.append((score, row))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in candidates]


def _inspection_high_quality_suggestion_samples(task_type: str, rows: list[dict[str, str]], *, limit: int = 8) -> list[dict[str, Any]]:
    sample_rows = _inspection_high_quality_suggestion_candidate_rows(task_type)
    samples: list[dict[str, Any]] = []
    for row in sample_rows[:limit]:
        samples.append(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "split_hint": str(row.get("split_hint") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "ocr_suggestion": str(row.get("ocr_suggestion") or "").strip(),
                "ocr_suggestion_quality": float(row.get("ocr_suggestion_quality") or 0.0),
                "ocr_suggestion_confidence": float(row.get("ocr_suggestion_confidence") or 0.0),
                "quality_score": _inspection_crop_quality_score(task_type, row),
                "review_status": str(row.get("review_status") or "pending").strip() or "pending",
                "review_origin_label": "高质量建议",
            }
        )
    return samples


def _inspection_readiness_blocker_samples(task_type: str, rows: list[dict[str, str]], *, limit: int = 8) -> list[dict[str, Any]]:
    sample_rows = _inspection_readiness_blocker_rows(task_type)
    samples: list[dict[str, Any]] = []
    for row in sample_rows[:limit]:
        samples.append(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "split_hint": str(row.get("split_hint") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "final_text": str(row.get("final_text") or "").strip(),
                "quality_score": _inspection_crop_quality_score(task_type, row),
                "review_status": str(row.get("review_status") or "pending").strip() or "pending",
                "review_origin_label": "训练阻断样本",
            }
        )
    return samples


def _get_inspection_state_blueprint_or_404(task_type: str) -> dict[str, Any]:
    blueprint = _get_inspection_blueprint_or_404(task_type)
    if not blueprint or str(blueprint.get("dataset_kind") or "").strip() != "state_classification":
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_state_task_not_found",
            "没有找到这类巡检状态工作区。",
            next_step="请确认任务类型是否为 door_lock_state_detect 或 connector_defect_detect，并确保蓝图配置已存在。",
        )
    return blueprint


def _inspection_state_labeling_item_summary(task_type: str, row: dict[str, str]) -> dict[str, Any]:
    blueprint = _get_inspection_state_blueprint_or_404(task_type)
    label_value = str(row.get("label_value") or row.get("final_label") or row.get("label_class") or "").strip()
    reviewer = str(row.get("reviewer") or "").strip()
    return {
        "sample_id": str(row.get("sample_id") or "").strip(),
        "asset_id": str(row.get("asset_id") or "").strip(),
        "task_type": task_type,
        "task_label": str(blueprint.get("label") or task_type),
        "split_hint": str(row.get("split_hint") or "").strip(),
        "source_file": str(row.get("source_file") or "").strip(),
        "crop_file": str(row.get("crop_file") or "").strip(),
        "label_class": str(row.get("label_class") or "").strip(),
        "label_value": label_value,
        "review_status": str(row.get("review_status") or "pending").strip() or "pending",
        "reviewer": reviewer,
        "notes": str(row.get("notes") or "").strip(),
        "bbox": [
            int(row.get("bbox_x1") or 0),
            int(row.get("bbox_y1") or 0),
            int(row.get("bbox_x2") or 0),
            int(row.get("bbox_y2") or 0),
        ],
        "has_label_value": bool(label_value),
        "label_values": list(blueprint.get("label_values") or []),
    }


def _inspection_state_item_sort_key(item: dict[str, Any]) -> tuple:
    review_status = str(item.get("review_status") or "")
    has_label = bool(item.get("has_label_value"))
    split = str(item.get("split_hint") or "")
    status_rank = {"needs_check": 0, "pending": 1, "done": 2}.get(review_status, 3)
    split_rank = {"validation": 0, "train": 1}.get(split, 2)
    return (
        status_rank,
        0 if not has_label else 1,
        split_rank,
        str(item.get("sample_id") or ""),
    )


def _inspection_state_review_candidate_rows(task_type: str) -> list[dict[str, str]]:
    rows = _load_inspection_labeling_rows(task_type)
    candidates: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        label_value = str(row.get("label_value") or row.get("final_label") or row.get("label_class") or "").strip()
        review_status = str(row.get("review_status") or "pending").strip() or "pending"
        if label_value and review_status == "done":
            continue
        score = _inspection_crop_quality_score(task_type, row)
        pending_rank = 0 if review_status == "needs_check" else 1 if review_status == "pending" else 2
        candidates.append((pending_rank * -1000 + score, row))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in candidates]


def _inspection_state_starter_samples(task_type: str, rows: list[dict[str, str]], *, limit: int = 8) -> list[dict[str, Any]]:
    ranked_rows = _inspection_state_review_candidate_rows(task_type)[:limit]
    samples: list[dict[str, Any]] = []
    for row in ranked_rows:
        samples.append(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "split_hint": str(row.get("split_hint") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "asset_id": str(row.get("asset_id") or "").strip(),
                "quality_score": _inspection_crop_quality_score(task_type, row),
                "review_status": str(row.get("review_status") or "pending").strip() or "pending",
                "label_value": str(row.get("label_value") or row.get("final_label") or "").strip(),
            }
        )
    return samples


def _render_inspection_state_review_queue_csv(task_type: str, rows: list[dict[str, str]]) -> str:
    blueprint = _get_inspection_state_blueprint_or_404(task_type)
    header = [
        "sample_id",
        "task_type",
        "split_hint",
        "asset_id",
        "source_file",
        "crop_file",
        "label_class",
        "label_options",
        "label_value",
        "review_status",
        "reviewer",
        "notes",
        "quality_score",
    ]
    sink = io.StringIO()
    writer = csv.DictWriter(sink, fieldnames=header)
    writer.writeheader()
    label_options = "|".join(str(item).strip() for item in list(blueprint.get("label_values") or []) if str(item).strip())
    for row in rows:
        writer.writerow(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "task_type": task_type,
                "split_hint": str(row.get("split_hint") or "").strip(),
                "asset_id": str(row.get("asset_id") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "label_class": str(row.get("label_class") or "").strip(),
                "label_options": label_options,
                "label_value": str(row.get("label_value") or row.get("final_label") or "").strip(),
                "review_status": str(row.get("review_status") or "").strip(),
                "reviewer": str(row.get("reviewer") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
                "quality_score": str(_inspection_crop_quality_score(task_type, row)),
            }
        )
    return sink.getvalue()


def _build_inspection_state_review_pack(task_type: str, rows: list[dict[str, str]]) -> bytes:
    blueprint = _get_inspection_state_blueprint_or_404(task_type)
    payload = io.BytesIO()
    csv_text = _render_inspection_state_review_queue_csv(task_type, rows)
    readme = "\n".join(
        [
            f"Inspection state review pack: {task_type}",
            "",
            f"任务名称：{str(blueprint.get('label') or task_type)}",
            f"可选标签：{' / '.join(str(item).strip() for item in list(blueprint.get('label_values') or [])) or '-'}",
            "",
            "包含内容：",
            "- state_review_queue.csv：待复核状态样本队列",
            "- crops/：当前裁剪图（如存在）",
            "- sources/：对应原图",
            "",
            "建议流程：",
            "1. 打开 state_review_queue.csv",
            "2. 结合 crops/ 和 sources/ 判断真实状态/缺陷标签",
            "3. 修改 label_value / review_status / reviewer / notes",
            "4. 在系统里先做“预检查离线复核 CSV”，确认会更新哪些样本",
            "5. 再使用“导入离线复核 CSV”正式导回",
            "",
            "注意：",
            "- label_value 必须使用 label_options 中提供的状态值",
            "- 看不清时请标记 needs_check，不要误填 done",
        ]
    )
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("state_review_queue.csv", csv_text)
        zf.writestr("README.txt", readme)
        manifest_path = _inspection_labeling_manifest_path(task_type)
        for row in rows:
            sample_id = str(row.get("sample_id") or "").strip() or secrets.token_hex(4)
            crop_path = _resolve_image_path({"crop_file": row.get("crop_file")}, manifest_path=manifest_path)
            if crop_path and crop_path.exists() and crop_path.is_file():
                ext = crop_path.suffix or ".jpg"
                zf.write(crop_path, arcname=f"crops/{sample_id}{ext}")
            source_path = _resolve_image_path({"source_file": row.get("source_file")}, manifest_path=manifest_path)
            if source_path and source_path.exists() and source_path.is_file():
                ext = source_path.suffix or ".jpg"
                zf.write(source_path, arcname=f"sources/{sample_id}{ext}")
    return payload.getvalue()


def _summarize_inspection_state_import(
    task_type: str,
    *,
    text: str,
    importer: str,
    apply_updates: bool,
) -> InspectionStateBulkImportSummary:
    blueprint = _get_inspection_state_blueprint_or_404(task_type)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "sample_id" not in reader.fieldnames:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_import_missing_columns",
            "导入 CSV 缺少必要列 sample_id。",
            next_step="请使用系统导出的状态复核队列表头，至少保留 sample_id 和 label_value。",
        )
    rows = _load_inspection_labeling_rows(task_type)
    if not rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_import_workspace_empty",
            "当前状态工作区没有可更新的样本。",
            next_step="请先导入真实图片资产，再导入离线复核 CSV。",
        )
    allowed_labels = {str(item).strip() for item in list(blueprint.get("label_values") or []) if str(item).strip()}
    row_index = {str(row.get("sample_id") or "").strip(): idx for idx, row in enumerate(rows)}
    total_rows = 0
    matched_rows = 0
    updated_rows = 0
    would_update_rows = 0
    skipped_rows = 0
    missing_sample_ids: list[str] = []
    unchanged_sample_ids: list[str] = []
    changed = False
    for incoming in reader:
        total_rows += 1
        sample_id = str(incoming.get("sample_id") or "").strip()
        if not sample_id:
            skipped_rows += 1
            continue
        idx = row_index.get(sample_id)
        if idx is None:
            missing_sample_ids.append(sample_id)
            continue
        matched_rows += 1
        label_value = str(incoming.get("label_value") or "").strip()
        if label_value and label_value not in allowed_labels:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "inspection_state_label_invalid",
                "导入 CSV 里出现了当前任务不允许的状态标签。",
                next_step="请把 label_value 改成系统导出队列里的 label_options 之一，再重新导入。",
                raw_detail={"sample_id": sample_id, "label_value": label_value},
            )
        review_status = str(incoming.get("review_status") or "").strip() or ("done" if label_value else "pending")
        reviewer = str(incoming.get("reviewer") or "").strip() or importer
        notes = str(incoming.get("notes") or "").strip()
        current = dict(rows[idx])
        next_row = dict(current)
        next_row["label_value"] = label_value
        next_row["final_label"] = label_value
        next_row["review_status"] = review_status
        next_row["reviewer"] = reviewer
        next_row["notes"] = notes
        if next_row == current:
            unchanged_sample_ids.append(sample_id)
            skipped_rows += 1
            continue
        if apply_updates:
            rows[idx] = next_row
            updated_rows += 1
            changed = True
        else:
            would_update_rows += 1
    if apply_updates and changed:
        _rewrite_inspection_labeling_files(task_type, rows)
    return InspectionStateBulkImportSummary(
        total_rows=total_rows,
        matched_rows=matched_rows,
        updated_rows=updated_rows,
        would_update_rows=would_update_rows,
        skipped_rows=skipped_rows,
        missing_sample_ids=missing_sample_ids[:20],
        unchanged_sample_ids=unchanged_sample_ids[:20],
    )


def _inspection_state_training_readiness(task_type: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    reviewed_rows = [
        row for row in rows
        if str(row.get("label_value") or row.get("final_label") or row.get("label_class") or "").strip()
    ]
    train_rows = sum(1 for row in reviewed_rows if str(row.get("split_hint") or "").strip() == "train")
    validation_rows = sum(1 for row in reviewed_rows if str(row.get("split_hint") or "").strip() == "validation")
    ready = len(reviewed_rows) >= 2 and train_rows > 0 and validation_rows > 0
    blockers: list[str] = []
    if len(reviewed_rows) < 2:
        blockers.append("reviewed_rows_not_enough")
    if train_rows == 0:
        blockers.append("train_split_missing")
    if validation_rows == 0:
        blockers.append("validation_split_missing")
    if ready:
        status_name = "ready"
        label = "可正常训练"
        next_step = "可以直接导出训练包、注册训练资产，或继续创建训练作业。"
    else:
        status_name = "blocked"
        label = "仍不可导出"
        next_step = "请先补足状态标签，并确保 train 和 validation 都至少各有 1 条。"
    return {
        "status": status_name,
        "label": label,
        "normal_export_ready": ready,
        "cold_start_export_ready": ready,
        "next_step": next_step,
        "blockers": blockers,
        "reviewed_rows": len(reviewed_rows),
        "train_rows": train_rows,
        "validation_rows": validation_rows,
    }


def _inspection_state_auto_split(existing_rows: list[dict[str, str]], offset: int) -> str:
    base = len(existing_rows) + offset
    return "validation" if base % 5 == 0 else "train"


def _import_inspection_state_assets(
    task_type: str,
    *,
    asset_ids: list[str],
    note: str | None,
    db: Session,
    current_user: AuthUser,
) -> dict[str, Any]:
    _get_inspection_state_blueprint_or_404(task_type)
    if is_supplier_user(current_user.roles):
        raise_ui_error(
            status.HTTP_403_FORBIDDEN,
            "inspection_state_asset_import_forbidden",
            "当前账号不能把原始资产导入巡检状态工作区。",
            next_step="请使用平台管理员或买家操作员账号，再从真实图片资产开始导入。",
        )
    normalized_asset_ids = _normalize_asset_ids(asset_ids)
    if not normalized_asset_ids:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_asset_ids_missing",
            "还没有填写要导入的图片资产编号。",
            next_step="请先选择 1 张或多张真实图片资产，再开始导入状态工作区。",
        )
    assets = _get_assets_or_400(db, normalized_asset_ids)
    if is_buyer_user(current_user.roles):
        invalid_scope = next((asset for asset in assets if asset.buyer_tenant_id != current_user.tenant_id), None)
        if invalid_scope:
            raise_ui_error(
                status.HTTP_403_FORBIDDEN,
                "inspection_state_asset_scope_forbidden",
                "当前账号只能导入自己租户范围内的图片资产。",
                next_step="请改用当前租户下的真实图片资产，或使用平台管理员账号操作。",
            )
    existing_rows = _load_inspection_labeling_rows(task_type)
    existing_asset_ids = {str(row.get("asset_id") or "").strip() for row in existing_rows if str(row.get("asset_id") or "").strip()}
    existing_sources = {str(row.get("source_file") or "").strip() for row in existing_rows if str(row.get("source_file") or "").strip()}
    appended_rows: list[dict[str, str]] = []
    skipped_asset_ids: list[str] = []
    note_suffix = str(note or "").strip()
    for index, asset in enumerate(assets):
        if asset.asset_type not in {"image", "screenshot"}:
            skipped_asset_ids.append(asset.id)
            continue
        source_file = str(asset.storage_uri or "").strip()
        if not source_file or asset.id in existing_asset_ids or source_file in existing_sources:
            skipped_asset_ids.append(asset.id)
            continue
        row = {
            "sample_id": f"{asset.id}__0001",
            "asset_id": asset.id,
            "source_file": source_file,
            "crop_file": "",
            "split_hint": _inspection_state_auto_split(existing_rows + appended_rows, index),
            "task_type": task_type,
            "label_class": "",
            "label_value": "",
            "bbox_x1": "",
            "bbox_y1": "",
            "bbox_x2": "",
            "bbox_y2": "",
            "review_status": "pending",
            "reviewer": "",
            "notes": f"从平台资产导入：{asset.file_name}" + (f" / {note_suffix}" if note_suffix else ""),
        }
        appended_rows.append(row)
        existing_asset_ids.add(asset.id)
        existing_sources.add(source_file)
    if not appended_rows and skipped_asset_ids:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_assets_already_imported",
            "这批图片资产已经在当前巡检状态工作区里了，未导入任何新样本。",
            next_step="请换一批新的真实图片资产，或直接进入状态复核继续补标签。",
        )
    if not appended_rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_assets_not_importable",
            "这批资产不能用于巡检状态工作区导入。",
            next_step="请确认资产类型为图片，并且当前账号对这些资产有访问权限。",
        )
    rows = existing_rows + appended_rows
    _rewrite_inspection_labeling_files(task_type, rows)
    return {
        "status": "ok",
        "task_type": task_type,
        "imported_rows": len(appended_rows),
        "skipped_asset_ids": skipped_asset_ids,
        "items": [_inspection_state_labeling_item_summary(task_type, row) for row in appended_rows[:20]],
    }


def _inspection_ocr_training_readiness(task_type: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    blueprint = _get_inspection_ocr_blueprint_or_404(task_type)
    reviewed_rows = [row for row in rows if str(row.get("final_text") or "").strip()]
    clean_rows = [
        row for row in reviewed_rows
        if str(row.get("reviewer") or "").strip()
        and str(row.get("reviewer") or "").strip() != "proxy_from_car_number_truth"
    ]
    proxy_rows = [
        row for row in reviewed_rows
        if str(row.get("reviewer") or "").strip() == "proxy_from_car_number_truth"
    ]
    clean_train = sum(1 for row in clean_rows if str(row.get("split_hint") or "").strip() == "train")
    clean_validation = sum(1 for row in clean_rows if str(row.get("split_hint") or "").strip() == "validation")
    all_train = sum(1 for row in reviewed_rows if str(row.get("split_hint") or "").strip() == "train")
    all_validation = sum(1 for row in reviewed_rows if str(row.get("split_hint") or "").strip() == "validation")
    readiness_rules = blueprint.get("training_readiness") if isinstance(blueprint.get("training_readiness"), dict) else {}
    min_manual_rows_for_ready = max(2, int(readiness_rules.get("min_manual_rows_for_ready") or 2))
    cold_start_ready = len(reviewed_rows) >= 2 and all_train > 0 and all_validation > 0
    normal_ready = len(proxy_rows) == 0 and len(clean_rows) >= min_manual_rows_for_ready and clean_train > 0 and clean_validation > 0
    blockers: list[str] = []
    if proxy_rows:
        blockers.append("proxy_truth_present")
    if len(clean_rows) < min_manual_rows_for_ready:
        blockers.append("manual_truth_not_enough")
    if clean_train == 0:
        blockers.append("manual_train_split_missing")
    if clean_validation == 0:
        blockers.append("manual_validation_split_missing")
    if normal_ready:
        status = "ready"
        label = "可正常训练"
        next_step = "可以直接导出训练包、注册训练资产，或继续创建训练作业。"
    elif cold_start_ready:
        status = "cold_start_only"
        label = "仅冷启动可训练"
        remaining_manual_rows = max(0, min_manual_rows_for_ready - len(clean_rows))
        if proxy_rows:
            next_step = f"当前可用于冷启动验证；还需要把 {len(proxy_rows)} 条代理回灌样本改成人工确认真值，并把人工真值补到至少 {min_manual_rows_for_ready} 条后，才能进入正式训练。"
        else:
            next_step = f"当前可用于冷启动验证；还需要再补 {remaining_manual_rows} 条人工确认真值后，才能进入正式训练。"
    else:
        status = "blocked"
        label = "仍不可导出"
        if proxy_rows:
            next_step = f"请先优先替换 {len(proxy_rows)} 条代理回灌样本，并把人工确认真值补到至少 {min_manual_rows_for_ready} 条。"
        else:
            remaining_manual_rows = max(0, min_manual_rows_for_ready - len(clean_rows))
            next_step = f"请继续补人工确认真值；还需要再补 {remaining_manual_rows} 条，并确保 train 和 validation 都至少各有 1 条。"
    replacement_progress_pct = round((len(clean_rows) / (len(clean_rows) + len(proxy_rows))) * 100, 1) if (len(clean_rows) + len(proxy_rows)) else 0.0
    manual_ready_progress_pct = round((min(len(clean_rows), min_manual_rows_for_ready) / min_manual_rows_for_ready) * 100, 1) if min_manual_rows_for_ready else 100.0
    suggestion_rows = [row for row in rows if str(row.get("ocr_suggestion") or "").strip()]
    high_quality_suggestion_rows = [
        row
        for row in suggestion_rows
        if float(row.get("ocr_suggestion_quality") or 0.0) >= 1.0
    ]
    high_quality_review_candidates = _inspection_high_quality_suggestion_candidate_rows(task_type)
    return {
        "status": status,
        "label": label,
        "normal_export_ready": normal_ready,
        "cold_start_export_ready": cold_start_ready,
        "next_step": next_step,
        "blockers": blockers,
        "manual_reviewed_rows": len(clean_rows),
        "proxy_seeded_rows": len(proxy_rows),
        "min_manual_rows_for_ready": min_manual_rows_for_ready,
        "remaining_manual_rows_for_ready": max(0, min_manual_rows_for_ready - len(clean_rows)),
        "clean_train_rows": clean_train,
        "clean_validation_rows": clean_validation,
        "reviewed_train_rows": all_train,
        "reviewed_validation_rows": all_validation,
        "replacement_progress_pct": replacement_progress_pct,
        "manual_ready_progress_pct": manual_ready_progress_pct,
        "remaining_proxy_rows": len(proxy_rows),
        "suggestion_rows": len(suggestion_rows),
        "high_quality_suggestion_rows": len(high_quality_suggestion_rows),
        "high_quality_review_candidate_rows": len(high_quality_review_candidates),
    }


def _inspection_ocr_readiness_action_plan(task_type: str, rows: list[dict[str, str]], readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    current = readiness or _inspection_ocr_training_readiness(task_type, rows)
    status_name = str(current.get("status") or "").strip() or "blocked"
    manual_reviewed_rows = int(current.get("manual_reviewed_rows") or 0)
    proxy_seeded_rows = int(current.get("proxy_seeded_rows") or 0)
    blocker_rows = len(_inspection_readiness_blocker_rows(task_type))
    remaining_manual_rows = int(current.get("remaining_manual_rows_for_ready") or 0)
    high_quality_rows = int(current.get("high_quality_review_candidate_rows") or 0)
    clean_train_rows = int(current.get("clean_train_rows") or 0)
    clean_validation_rows = int(current.get("clean_validation_rows") or 0)
    min_manual_rows = int(current.get("min_manual_rows_for_ready") or 2)

    projected_manual_reviewed_rows = manual_reviewed_rows + blocker_rows
    projected_clean_train_rows = clean_train_rows + min(
        blocker_rows,
        max(0, int(current.get("reviewed_train_rows") or 0) - clean_train_rows),
    )
    projected_clean_validation_rows = clean_validation_rows + max(
        0,
        blocker_rows - min(
            blocker_rows,
            max(0, int(current.get("reviewed_train_rows") or 0) - clean_train_rows),
        ),
    )
    projected_ready_after_blockers = (
        blocker_rows > 0
        and projected_manual_reviewed_rows >= min_manual_rows
        and projected_clean_train_rows > 0
        and projected_clean_validation_rows > 0
    )

    if status_name == "ready":
        title = "已经满足正式训练条件"
        summary = "当前人工确认真值和切分都已达标，可以直接进入正式训练或继续扩大样本规模。"
        primary_action = "start_normal_training"
        steps = [
            "继续抽查最近确认的真值，确保标签稳定。",
            "直接导出正式训练包或创建下一轮训练作业。",
        ]
    elif blocker_rows > 0:
        title = "先处理训练阻断样本"
        summary = f"当前最优先的是把 {blocker_rows} 条训练阻断样本改成真实真值或人工确认当前文本，这一步会直接影响是否能进入正式训练。"
        primary_action = "resolve_readiness_blockers"
        steps = [
            f"先打开训练阻断样本，逐条替换或确认这 {blocker_rows} 条代理回灌样本。",
            "如果当前文本可信，可优先批量确认代理真值；不可信时改写 final_text。",
            f"处理完后，再补足剩余人工真值，目标至少 {min_manual_rows} 条。",
        ]
    elif high_quality_rows > 0:
        title = "优先确认高质量建议"
        summary = f"当前没有代理阻断，但还有 {high_quality_rows} 条高质量建议可快速转成人工真值，先处理这批样本能最快提升训练准备度。"
        primary_action = "accept_high_quality_suggestions"
        steps = [
            "先打开高质量建议队列，优先确认建议最清晰的样本。",
            f"把人工确认真值补到至少 {min_manual_rows} 条，并保证 train / validation 都有样本。",
        ]
    else:
        title = "继续补真实真值"
        summary = "当前没有明显的捷径样本可直接确认，需要继续逐条补真实 final_text 才能推进训练准备度。"
        primary_action = "review_more_samples"
        steps = [
            "先从优先起步样本开始，补最清晰的 crop。",
            f"把人工确认真值补到至少 {min_manual_rows} 条，并保证 train / validation 都有样本。",
        ]

    if status_name == "cold_start_only":
        projected_status = "ready" if projected_ready_after_blockers else "cold_start_only"
    elif status_name == "blocked":
        projected_status = "cold_start_only" if blocker_rows == 0 and remaining_manual_rows > 0 else ("ready" if projected_ready_after_blockers else "blocked")
    else:
        projected_status = "ready"

    return {
        "title": title,
        "summary": summary,
        "primary_action": primary_action,
        "steps": steps,
        "projected_status_after_blockers": projected_status,
        "projected_ready_after_blockers": projected_ready_after_blockers,
        "projected_manual_reviewed_rows": projected_manual_reviewed_rows,
        "remaining_manual_rows_after_blockers": max(0, min_manual_rows - projected_manual_reviewed_rows),
    }


def _render_inspection_proxy_queue_csv(task_type: str, rows: list[dict[str, str]]) -> str:
    header = [
        "sample_id",
        "task_type",
        "split_hint",
        "source_file",
        "crop_file",
        "final_text",
        "review_status",
        "reviewer",
        "notes",
        "quality_score",
    ]
    sink = io.StringIO()
    writer = csv.DictWriter(sink, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "task_type": task_type,
                "split_hint": str(row.get("split_hint") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "final_text": str(row.get("final_text") or "").strip(),
                "review_status": str(row.get("review_status") or "").strip(),
                "reviewer": str(row.get("reviewer") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
                "quality_score": str(_inspection_crop_quality_score(task_type, row)),
            }
        )
    return sink.getvalue()


def _render_inspection_high_quality_queue_csv(task_type: str, rows: list[dict[str, str]]) -> str:
    header = [
        "sample_id",
        "task_type",
        "split_hint",
        "source_file",
        "crop_file",
        "ocr_suggestion",
        "ocr_suggestion_quality",
        "ocr_suggestion_confidence",
        "final_text",
        "review_status",
        "reviewer",
        "notes",
        "quality_score",
    ]
    sink = io.StringIO()
    writer = csv.DictWriter(sink, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "task_type": task_type,
                "split_hint": str(row.get("split_hint") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "ocr_suggestion": str(row.get("ocr_suggestion") or "").strip(),
                "ocr_suggestion_quality": str(row.get("ocr_suggestion_quality") or "").strip(),
                "ocr_suggestion_confidence": str(row.get("ocr_suggestion_confidence") or "").strip(),
                "final_text": str(row.get("final_text") or "").strip(),
                "review_status": str(row.get("review_status") or "").strip(),
                "reviewer": str(row.get("reviewer") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
                "quality_score": str(_inspection_crop_quality_score(task_type, row)),
            }
        )
    return sink.getvalue()


def _build_inspection_proxy_review_pack(task_type: str, rows: list[dict[str, str]]) -> bytes:
    payload = io.BytesIO()
    csv_text = _render_inspection_proxy_queue_csv(task_type, rows)
    readme = "\n".join(
        [
            f"Inspection OCR proxy replacement pack: {task_type}",
            "",
            "包含内容：",
            "- proxy_replacement_queue.csv：待替换代理真值队列",
            "- crops/：当前裁剪图",
            "- sources/：对应原图（若存在）",
            "",
            "建议流程：",
            "1. 打开 proxy_replacement_queue.csv",
            "2. 结合 crops/ 和 sources/ 人工确认真实文本",
            "3. 修改 final_text / review_status / reviewer / notes",
            "4. 在系统里使用“导入离线复核 CSV”批量导回",
            "",
            "注意：",
            "- 当前导出的 final_text 可能仍是代理回灌文本，只能作为参考",
            "- 未看清时请改为 needs_check，不要保留错误真值",
        ]
    )
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("proxy_replacement_queue.csv", csv_text)
        zf.writestr("README.txt", readme)
        manifest_path = _inspection_labeling_manifest_path(task_type)
        for row in rows:
            sample_id = str(row.get("sample_id") or "").strip() or secrets.token_hex(4)
            crop_path = _resolve_image_path({"crop_file": row.get("crop_file")}, manifest_path=manifest_path)
            if crop_path and crop_path.exists() and crop_path.is_file():
                ext = crop_path.suffix or ".jpg"
                zf.write(crop_path, arcname=f"crops/{sample_id}{ext}")
            source_path = _resolve_image_path({"source_file": row.get("source_file")}, manifest_path=manifest_path)
            if source_path and source_path.exists() and source_path.is_file():
                ext = source_path.suffix or ".jpg"
                zf.write(source_path, arcname=f"sources/{sample_id}{ext}")
    return payload.getvalue()


def _build_inspection_high_quality_review_pack(task_type: str, rows: list[dict[str, str]]) -> bytes:
    payload = io.BytesIO()
    csv_text = _render_inspection_high_quality_queue_csv(task_type, rows)
    readme = "\n".join(
        [
            f"Inspection OCR high-quality suggestion pack: {task_type}",
            "",
            "包含内容：",
            "- high_quality_suggestion_queue.csv：高质量建议待确认队列",
            "- crops/：当前裁剪图",
            "- sources/：对应原图（若存在）",
            "",
            "建议流程：",
            "1. 优先浏览这批高质量建议样本",
            "2. 结合 crops/ 和 sources/ 判断 OCR 建议是否可直接采纳",
            "3. 在 CSV 中填写或修正 final_text / review_status / reviewer / notes",
            "4. 回到系统使用“导入离线复核 CSV”批量导回",
            "",
            "注意：",
            "- 高质量建议仍然只是建议，不等于真值",
            "- 看不清时请标记 needs_check，不要直接保存为 done",
        ]
    )
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("high_quality_suggestion_queue.csv", csv_text)
        zf.writestr("README.txt", readme)
        manifest_path = _inspection_labeling_manifest_path(task_type)
        for row in rows:
            sample_id = str(row.get("sample_id") or "").strip() or secrets.token_hex(4)
            crop_path = _resolve_image_path({"crop_file": row.get("crop_file")}, manifest_path=manifest_path)
            if crop_path and crop_path.exists() and crop_path.is_file():
                ext = crop_path.suffix or ".jpg"
                zf.write(crop_path, arcname=f"crops/{sample_id}{ext}")
            source_path = _resolve_image_path({"source_file": row.get("source_file")}, manifest_path=manifest_path)
            if source_path and source_path.exists() and source_path.is_file():
                ext = source_path.suffix or ".jpg"
                zf.write(source_path, arcname=f"sources/{sample_id}{ext}")
    return payload.getvalue()


def _render_inspection_readiness_blocker_queue_csv(task_type: str, rows: list[dict[str, str]]) -> str:
    header = [
        "sample_id",
        "task_type",
        "split_hint",
        "source_file",
        "crop_file",
        "final_text",
        "review_status",
        "reviewer",
        "notes",
        "quality_score",
        "blocker_reason",
    ]
    sink = io.StringIO()
    writer = csv.DictWriter(sink, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "sample_id": str(row.get("sample_id") or "").strip(),
                "task_type": task_type,
                "split_hint": str(row.get("split_hint") or "").strip(),
                "source_file": str(row.get("source_file") or "").strip(),
                "crop_file": str(row.get("crop_file") or "").strip(),
                "final_text": str(row.get("final_text") or "").strip(),
                "review_status": str(row.get("review_status") or "").strip(),
                "reviewer": str(row.get("reviewer") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
                "quality_score": str(_inspection_crop_quality_score(task_type, row)),
                "blocker_reason": _inspection_readiness_blocker_reason(row),
            }
        )
    return sink.getvalue()


def _build_inspection_readiness_blocker_pack(task_type: str, rows: list[dict[str, str]]) -> bytes:
    payload = io.BytesIO()
    csv_text = _render_inspection_readiness_blocker_queue_csv(task_type, rows)
    readme = "\n".join(
        [
            f"Inspection OCR readiness blocker pack: {task_type}",
            "",
            "包含内容：",
            "- readiness_blocker_queue.csv：当前阻断正式训练的样本队列",
            "- crops/：当前裁剪图",
            "- sources/：对应原图（若存在）",
            "",
            "建议流程：",
            "1. 优先处理这批样本，它们直接阻断当前任务进入“可正常训练”",
            "2. 对照 crops/ 和 sources/ 判断 final_text 是否为真实真值",
            "3. 若当前 final_text 可信，可在系统里批量确认代理真值",
            "4. 若不可信，请修正 final_text 后再导回工作区",
            "",
            "注意：",
            "- 这批样本不等于所有待处理样本，而是当前真正阻断正式训练的样本",
            "- 当前 blocker_reason=proxy_seeded_truth，后续可扩展为更多门禁原因",
        ]
    )
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("readiness_blocker_queue.csv", csv_text)
        zf.writestr("README.txt", readme)
        manifest_path = _inspection_labeling_manifest_path(task_type)
        for row in rows:
            sample_id = str(row.get("sample_id") or "").strip() or secrets.token_hex(4)
            crop_path = _resolve_image_path({"crop_file": row.get("crop_file")}, manifest_path=manifest_path)
            if crop_path and crop_path.exists() and crop_path.is_file():
                ext = crop_path.suffix or ".jpg"
                zf.write(crop_path, arcname=f"crops/{sample_id}{ext}")
            source_path = _resolve_image_path({"source_file": row.get("source_file")}, manifest_path=manifest_path)
            if source_path and source_path.exists() and source_path.is_file():
                ext = source_path.suffix or ".jpg"
                zf.write(source_path, arcname=f"sources/{sample_id}{ext}")
    return payload.getvalue()


def _summarize_inspection_ocr_import(
    task_type: str,
    *,
    text: str,
    importer: str,
    apply_updates: bool,
) -> InspectionOcrBulkImportSummary:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "sample_id" not in reader.fieldnames:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_import_missing_columns",
            "导入 CSV 缺少必要列 sample_id。",
            next_step="请使用系统导出的代理替换队列表头，至少保留 sample_id 和 final_text。",
        )
    rows = _load_inspection_labeling_rows(task_type)
    if not rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_import_workspace_empty",
            "当前工作区没有可更新的样本。",
            next_step="请先生成巡检 OCR 工作区，再导入复核 CSV。",
        )
    row_index = {str(row.get("sample_id") or "").strip(): idx for idx, row in enumerate(rows)}
    total_rows = 0
    matched_rows = 0
    updated_rows = 0
    would_update_rows = 0
    skipped_rows = 0
    missing_sample_ids: list[str] = []
    unchanged_sample_ids: list[str] = []
    changed = False
    for incoming in reader:
        total_rows += 1
        sample_id = str(incoming.get("sample_id") or "").strip()
        if not sample_id:
            skipped_rows += 1
            continue
        idx = row_index.get(sample_id)
        if idx is None:
            missing_sample_ids.append(sample_id)
            continue
        matched_rows += 1
        final_text = str(incoming.get("final_text") or "").strip().upper()
        review_status = str(incoming.get("review_status") or "").strip() or ("done" if final_text else "pending")
        reviewer = str(incoming.get("reviewer") or "").strip() or importer
        notes = str(incoming.get("notes") or "").strip()
        current = dict(rows[idx])
        next_row = dict(current)
        next_row["final_text"] = final_text
        next_row["review_status"] = review_status
        next_row["reviewer"] = reviewer
        next_row["notes"] = notes
        if next_row == current:
            unchanged_sample_ids.append(sample_id)
            skipped_rows += 1
            continue
        if apply_updates:
            rows[idx] = next_row
            updated_rows += 1
            changed = True
        else:
            would_update_rows += 1
    if apply_updates and changed:
        _rewrite_inspection_labeling_files(task_type, rows)
    return InspectionOcrBulkImportSummary(
        total_rows=total_rows,
        matched_rows=matched_rows,
        updated_rows=updated_rows,
        would_update_rows=would_update_rows,
        skipped_rows=skipped_rows,
        missing_sample_ids=missing_sample_ids[:20],
        unchanged_sample_ids=unchanged_sample_ids[:20],
    )


def _summarize_inspection_high_quality_accept(
    task_type: str,
    *,
    sample_ids: list[str],
    limit: int,
    reviewer: str,
    notes: str,
    apply_updates: bool,
) -> InspectionOcrBulkAcceptHighQualitySummary:
    rows = _load_inspection_labeling_rows(task_type)
    if not rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_workspace_empty",
            "当前巡检文字工作区没有可处理的样本。",
            next_step="请先生成代理裁剪和 OCR 建议，再进行批量确认。",
        )
    candidate_rows = _inspection_high_quality_suggestion_candidate_rows(task_type)
    candidate_index = {
        str(row.get("sample_id") or "").strip(): row
        for row in candidate_rows
    }
    total_candidates = len(candidate_rows)
    explicit_ids = [str(sample_id or "").strip() for sample_id in sample_ids if str(sample_id or "").strip()]
    unmatched_sample_ids: list[str] = []
    if explicit_ids:
        selected_source = []
        for sample_id in explicit_ids:
            row = candidate_index.get(sample_id)
            if row is None:
                unmatched_sample_ids.append(sample_id)
                continue
            selected_source.append(row)
    else:
        selected_source = candidate_rows[:limit]
    selected_rows = selected_source[:limit]
    if not selected_rows and not unmatched_sample_ids:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_high_quality_empty",
            "当前没有可批量确认的高质量建议样本。",
            next_step="请先生成更多高质量建议，或放宽筛选条件后再试。",
        )
    row_index = {str(row.get("sample_id") or "").strip(): idx for idx, row in enumerate(rows)}
    changed_sample_ids: list[str] = []
    unchanged_sample_ids: list[str] = []
    updated_rows = 0
    would_update_rows = 0
    skipped_rows = 0
    changed = False
    for source_row in selected_rows:
        sample_id = str(source_row.get("sample_id") or "").strip()
        idx = row_index.get(sample_id)
        if idx is None:
            unmatched_sample_ids.append(sample_id)
            continue
        suggestion = str(source_row.get("ocr_suggestion") or "").strip().upper()
        if not suggestion:
            skipped_rows += 1
            unchanged_sample_ids.append(sample_id)
            continue
        current = dict(rows[idx])
        next_row = dict(current)
        next_row["final_text"] = suggestion
        next_row["review_status"] = "done"
        next_row["reviewer"] = reviewer
        next_row["notes"] = notes or "已批量接受高质量 OCR 建议"
        if next_row == current:
            unchanged_sample_ids.append(sample_id)
            skipped_rows += 1
            continue
        changed_sample_ids.append(sample_id)
        if apply_updates:
            rows[idx] = next_row
            updated_rows += 1
            changed = True
        else:
            would_update_rows += 1
    if apply_updates and changed:
        _rewrite_inspection_labeling_files(task_type, rows)
    return InspectionOcrBulkAcceptHighQualitySummary(
        total_candidates=total_candidates,
        selected_rows=len(selected_rows),
        updated_rows=updated_rows,
        would_update_rows=would_update_rows,
        skipped_rows=skipped_rows,
        unmatched_sample_ids=unmatched_sample_ids[:20],
        changed_sample_ids=changed_sample_ids[:20],
        unchanged_sample_ids=unchanged_sample_ids[:20],
    )


def _summarize_inspection_proxy_confirm(
    task_type: str,
    *,
    sample_ids: list[str],
    limit: int,
    reviewer: str,
    notes: str,
    apply_updates: bool,
) -> InspectionOcrBulkConfirmProxySummary:
    rows = _load_inspection_labeling_rows(task_type)
    if not rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_workspace_empty",
            "当前巡检文字工作区没有可处理的样本。",
            next_step="请先生成代理裁剪和 OCR 建议，再进行人工确认。",
        )
    candidate_rows = _inspection_proxy_seeded_rows(task_type)
    candidate_index = {
        str(row.get("sample_id") or "").strip(): row
        for row in candidate_rows
    }
    total_candidates = len(candidate_rows)
    explicit_ids = [str(sample_id or "").strip() for sample_id in sample_ids if str(sample_id or "").strip()]
    unmatched_sample_ids: list[str] = []
    if explicit_ids:
        selected_source = []
        for sample_id in explicit_ids:
            row = candidate_index.get(sample_id)
            if row is None:
                unmatched_sample_ids.append(sample_id)
                continue
            selected_source.append(row)
    else:
        selected_source = candidate_rows[:limit]
    selected_rows = selected_source[:limit]
    if not selected_rows and not unmatched_sample_ids:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_proxy_confirm_empty",
            "当前没有可人工确认的代理回灌样本。",
            next_step="请先切到“代理回灌”队列，或继续补更多待确认样本后再试。",
        )
    row_index = {str(row.get("sample_id") or "").strip(): idx for idx, row in enumerate(rows)}
    changed_sample_ids: list[str] = []
    unchanged_sample_ids: list[str] = []
    updated_rows = 0
    would_update_rows = 0
    skipped_rows = 0
    changed = False
    for source_row in selected_rows:
        sample_id = str(source_row.get("sample_id") or "").strip()
        idx = row_index.get(sample_id)
        if idx is None:
            unmatched_sample_ids.append(sample_id)
            continue
        current = dict(rows[idx])
        final_text = str(current.get("final_text") or "").strip().upper()
        if not final_text:
            skipped_rows += 1
            unchanged_sample_ids.append(sample_id)
            continue
        next_row = dict(current)
        next_row["final_text"] = final_text
        next_row["review_status"] = "done"
        next_row["reviewer"] = reviewer
        existing_notes = str(current.get("notes") or "").strip()
        confirmation_note = notes or "已人工复核确认，保留当前文本作为真实真值"
        next_row["notes"] = f"{existing_notes} / {confirmation_note}".strip(" /")
        if next_row == current:
            unchanged_sample_ids.append(sample_id)
            skipped_rows += 1
            continue
        changed_sample_ids.append(sample_id)
        if apply_updates:
            rows[idx] = next_row
            updated_rows += 1
            changed = True
        else:
            would_update_rows += 1
    if apply_updates and changed:
        _rewrite_inspection_labeling_files(task_type, rows)
    return InspectionOcrBulkConfirmProxySummary(
        total_candidates=total_candidates,
        selected_rows=len(selected_rows),
        updated_rows=updated_rows,
        would_update_rows=would_update_rows,
        skipped_rows=skipped_rows,
        unmatched_sample_ids=unmatched_sample_ids[:20],
        changed_sample_ids=changed_sample_ids[:20],
        unchanged_sample_ids=unchanged_sample_ids[:20],
    )


def _summarize_inspection_readiness_blocker_resolution(
    task_type: str,
    *,
    sample_ids: list[str],
    limit: int,
    reviewer: str,
    notes: str,
    apply_updates: bool,
) -> InspectionOcrBulkResolveBlockerSummary:
    rows = _load_inspection_labeling_rows(task_type)
    if not rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_workspace_empty",
            "当前巡检文字工作区没有可处理的样本。",
            next_step="请先生成代理裁剪和 OCR 建议，再继续处理训练阻断样本。",
        )
    candidate_rows = _inspection_readiness_blocker_rows(task_type)
    candidate_index = {str(row.get("sample_id") or "").strip(): row for row in candidate_rows}
    total_blockers = len(candidate_rows)
    explicit_ids = [str(sample_id or "").strip() for sample_id in sample_ids if str(sample_id or "").strip()]
    unmatched_sample_ids: list[str] = []
    if explicit_ids:
        selected_source: list[dict[str, str]] = []
        for sample_id in explicit_ids:
            row = candidate_index.get(sample_id)
            if row is None:
                unmatched_sample_ids.append(sample_id)
                continue
            selected_source.append(row)
    else:
        selected_source = candidate_rows[:limit]
    selected_rows = selected_source[:limit]
    if not selected_rows and not unmatched_sample_ids:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_readiness_blocker_empty",
            "当前没有可批量处理的训练阻断样本。",
            next_step="请先处理代理回灌样本，或等待新的训练阻断样本出现后再继续。",
        )
    row_index = {str(row.get("sample_id") or "").strip(): idx for idx, row in enumerate(rows)}
    changed_sample_ids: list[str] = []
    unchanged_sample_ids: list[str] = []
    resolved_reasons: set[str] = set()
    updated_rows = 0
    would_update_rows = 0
    skipped_rows = 0
    changed = False
    for source_row in selected_rows:
        sample_id = str(source_row.get("sample_id") or "").strip()
        idx = row_index.get(sample_id)
        if idx is None:
            unmatched_sample_ids.append(sample_id)
            continue
        blocker_reason = _inspection_readiness_blocker_reason(source_row)
        resolved_reasons.add(blocker_reason)
        current = dict(rows[idx])
        final_text = str(current.get("final_text") or "").strip().upper()
        if not final_text:
            skipped_rows += 1
            unchanged_sample_ids.append(sample_id)
            continue
        next_row = dict(current)
        next_row["final_text"] = final_text
        next_row["review_status"] = "done"
        next_row["reviewer"] = reviewer
        existing_notes = str(current.get("notes") or "").strip()
        if blocker_reason == "proxy_seeded_truth":
            blocker_note = notes or "已优先处理训练阻断样本，确认当前文本可作为真实真值"
        else:
            blocker_note = notes or f"已处理训练阻断样本（{blocker_reason}）"
        next_row["notes"] = f"{existing_notes} / {blocker_note}".strip(" /")
        if next_row == current:
            unchanged_sample_ids.append(sample_id)
            skipped_rows += 1
            continue
        changed_sample_ids.append(sample_id)
        if apply_updates:
            rows[idx] = next_row
            updated_rows += 1
            changed = True
        else:
            would_update_rows += 1
    if apply_updates and changed:
        _rewrite_inspection_labeling_files(task_type, rows)
    return InspectionOcrBulkResolveBlockerSummary(
        total_blockers=total_blockers,
        selected_rows=len(selected_rows),
        updated_rows=updated_rows,
        would_update_rows=would_update_rows,
        skipped_rows=skipped_rows,
        unmatched_sample_ids=unmatched_sample_ids[:20],
        changed_sample_ids=changed_sample_ids[:20],
        unchanged_sample_ids=unchanged_sample_ids[:20],
        resolved_reasons=sorted(reason for reason in resolved_reasons if reason),
    )


_INSPECTION_DATASET_MODULE: Any | None = None


def _load_inspection_dataset_builder_module() -> Any:
    global _INSPECTION_DATASET_MODULE
    if _INSPECTION_DATASET_MODULE is not None:
        return _INSPECTION_DATASET_MODULE
    script_path = REPO_ROOT / "docker" / "scripts" / "build_inspection_task_dataset.py"
    spec = importlib.util.spec_from_file_location("vistral_build_inspection_task_dataset", script_path)
    if spec is None or spec.loader is None:
        raise_ui_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "inspection_dataset_builder_unavailable",
            "巡检任务训练包生成器不可用。",
            next_step="请检查 docker/scripts/build_inspection_task_dataset.py 是否存在，再重试。",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _INSPECTION_DATASET_MODULE = module
    return module


def _export_inspection_ocr_dataset(task_type: str, *, allow_suggestions: bool) -> dict[str, Any]:
    _get_inspection_ocr_blueprint_or_404(task_type)
    module = _load_inspection_dataset_builder_module()
    manifest_path = _inspection_labeling_manifest_path(task_type)
    output_dir = _inspection_dataset_output_dir(task_type)
    try:
        return module.build_bundles(
            task_type=task_type,
            manifest_path=manifest_path,
            output_dir=output_dir,
            allow_suggestions=allow_suggestions,
        )
    except ValueError as exc:
        detail = str(exc)
        if "need at least 2 reviewed rows" in detail:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "inspection_ocr_dataset_not_enough_rows",
                "可用于导出训练数据的已确认文本样本还不够。",
                next_step="请先继续复核更多文本，至少准备训练集和验证集的有效样本。",
                raw_detail=detail,
            )
        if "both train and validation rows are required" in detail:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "inspection_ocr_dataset_split_missing",
                "导出训练包时需要同时具备训练集和验证集样本。",
                next_step="请确认 manifest 里同时有 train 和 validation 两种切分后再导出。",
                raw_detail=detail,
            )
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_dataset_export_failed",
            "巡检文字训练包导出失败。",
            next_step="请检查复核文本、切分字段和 crop 文件后再重试。",
            raw_detail=detail,
        )


def _ensure_inspection_proxy_seeded_allowed(task_type: str, *, allow_proxy_seeded: bool) -> None:
    if allow_proxy_seeded:
        return
    rows = _load_inspection_labeling_rows(task_type)
    proxy_rows = [
        row
        for row in rows
        if str(row.get("reviewer") or "").strip() == "proxy_from_car_number_truth"
        and str(row.get("final_text") or "").strip()
    ]
    if not proxy_rows:
        return
    raise_ui_error(
        status.HTTP_400_BAD_REQUEST,
        "inspection_ocr_proxy_truth_present",
        "当前工作区里还有代理回灌真值，默认不建议直接导出训练包。",
        next_step="请先在巡检文字复核页使用“仅看代理回灌 / 优先替换代理真值”把这些样本替换成真实标记文本；如果只是做冷启动验证，再勾选“允许带代理真值继续训练”。",
        raw_detail={
            "task_type": task_type,
            "proxy_seeded_rows": len(proxy_rows),
            "sample_ids": [str(row.get("sample_id") or "").strip() for row in proxy_rows[:8]],
        },
    )


def _default_inspection_ocr_training_spec(task_type: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    trainer_by_task = {
        "inspection_mark_ocr": "inspection_mark_ocr_local",
        "performance_mark_ocr": "performance_mark_ocr_local",
    }
    base = {
        "trainer": trainer_by_task.get(task_type, "inspection_ocr_local"),
        "epochs": 6,
        "learning_rate": 0.0005,
        "batch_size": 12,
        "image_size": [224, 96],
        "text_head": "ctc",
        "augmentation": {
            "motion_blur": 0.12,
            "brightness": 0.18,
            "contrast": 0.18,
            "perspective": 0.1,
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


def _default_inspection_state_training_spec(task_type: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    trainer_by_task = {
        "door_lock_state_detect": "door_lock_state_local",
        "connector_defect_detect": "connector_defect_local",
    }
    base = {
        "trainer": trainer_by_task.get(task_type, "inspection_state_local"),
        "epochs": 8,
        "learning_rate": 0.0003,
        "batch_size": 16,
        "image_size": [224, 224],
        "classification_head": "softmax",
        "augmentation": {
            "brightness": 0.12,
            "contrast": 0.12,
            "horizontal_shift": 0.05,
            "crop": 0.08,
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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "ocr_text_dataset_not_enough_rows",
            "可用于导出训练数据的已确认样本还不够。",
            next_step="请先继续复核更多车号文本，至少准备训练集和验证集的有效样本。",
        )
    train_rows = [row for row in accepted if str(row.get("split_hint") or "") == "train"]
    validation_rows = [row for row in accepted if str(row.get("split_hint") or "") == "validation"]
    if not train_rows or not validation_rows:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "ocr_text_dataset_split_missing",
            "导出训练数据时需要同时具备训练集和验证集样本。",
            next_step="请确认样本里同时有 train 和 validation 两种切分后再导出。",
        )
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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "ocr_dataset_bundle_invalid",
            "生成出来的 OCR 数据包格式不正确。",
            next_step="请重新导出一次训练数据；如果仍然失败，请检查原始标注清单是否完整。",
            raw_detail=str(exc),
        )

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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "ocr_dataset_bundle_not_found",
            "刚导出的 OCR 数据包文件不存在。",
            next_step="请重新执行一次导出训练数据，确认导出完成后再继续。",
        )
    if sensitivity_level not in {"L1", "L2", "L3"}:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "sensitivity_level_invalid",
            "敏感等级无效。",
            next_step="请把敏感等级改成 L1、L2 或 L3 之一。",
        )

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


def _register_inspection_ocr_dataset_asset(
    *,
    task_type: str,
    task_label: str,
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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_ocr_dataset_bundle_not_found",
            "刚导出的巡检文字数据包文件不存在。",
            next_step="请重新执行一次导出训练数据，确认导出完成后再继续。",
        )
    if sensitivity_level not in {"L1", "L2", "L3"}:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "sensitivity_level_invalid",
            "敏感等级无效。",
            next_step="请把敏感等级改成 L1、L2 或 L3 之一。",
        )

    settings = get_settings()
    os.makedirs(settings.asset_repo_path, exist_ok=True)
    asset_id = str(uuid.uuid4())
    ext = source_bundle.suffix or ".zip"
    target_path = Path(settings.asset_repo_path) / f"{asset_id}{ext}"
    checksum, file_size = _copy_file_with_checksum(source_bundle, target_path)
    dataset_label = str(bundle_summary.get("dataset_label") or f"{task_type}-{asset_purpose}").strip()
    source_uri = f"vistral://training/inspection-ocr/{task_type}/export-dataset/{asset_purpose}"
    meta = {
        "size": file_size,
        "extension": ext,
        "asset_purpose": asset_purpose,
        "dataset_label": dataset_label,
        "use_case": use_case,
        "intended_model_code": intended_model_code,
        "task_type": task_type,
        "task_label": task_label,
        "label_sources": export_summary.get("label_sources") or {},
        "reviewer_counts": export_summary.get("reviewer_counts") or {},
        "proxy_seeded_rows": int(export_summary.get("proxy_seeded_rows") or 0),
        "generated_from": f"{task_type}_labeling_review",
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
                "generated_from": f"{task_type}_labeling_review",
            },
            request=request,
            actor=current_user,
        )

    version_summary = {
        "task_type": task_type,
        "task_label": task_label,
        "resource_count": bundle_summary.get("sample_count") or 0,
        "task_count": bundle_summary.get("sample_count") or 0,
        "reviewed_task_count": bundle_summary.get("sample_count") or 0,
        "label_vocab": [str(task_type)],
        "label_sources": export_summary.get("label_sources") or {},
        "reviewer_counts": export_summary.get("reviewer_counts") or {},
        "proxy_seeded_rows": int(export_summary.get("proxy_seeded_rows") or 0),
        "generated_from": f"{task_type}_labeling_review",
        "generated_at": export_summary.get("generated_at"),
        "accepted_rows": export_summary.get("accepted_rows"),
        "skipped_missing_label": export_summary.get("skipped_missing_label"),
    }
    dataset_version = create_dataset_version_record(
        db,
        asset=asset,
        dataset_label=dataset_label,
        dataset_key=str(bundle_summary.get("dataset_key") or dataset_label),
        asset_purpose=asset_purpose,
        source_type="inspection_ocr_export",
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
            "source_type": "inspection_ocr_export",
            "task_type": task_type,
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


def _export_inspection_ocr_assets_internal(
    *,
    task_type: str,
    payload: InspectionOcrDatasetAssetImportRequest,
    request: Request,
    db: Session,
    current_user: AuthUser,
) -> dict[str, Any]:
    blueprint = _get_inspection_ocr_blueprint_or_404(task_type)
    _ensure_inspection_proxy_seeded_allowed(task_type, allow_proxy_seeded=payload.allow_proxy_seeded)
    export_summary = _export_inspection_ocr_dataset(task_type, allow_suggestions=payload.allow_suggestions)
    intended_model_code = str(payload.intended_model_code or "").strip() or task_type
    use_case = str(payload.use_case or "").strip() or f"railcar-{task_type.replace('_', '-')}"
    train_bundle = export_summary.get("bundles", {}).get("train") or {}
    validation_bundle = export_summary.get("bundles", {}).get("validation") or {}
    train_asset = _register_inspection_ocr_dataset_asset(
        task_type=task_type,
        task_label=str(blueprint.get("label") or task_type),
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
    validation_asset = _register_inspection_ocr_dataset_asset(
        task_type=task_type,
        task_label=str(blueprint.get("label") or task_type),
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
        "task_type": task_type,
        "task_label": str(blueprint.get("label") or task_type),
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


def _export_inspection_state_dataset(task_type: str) -> dict[str, Any]:
    _get_inspection_state_blueprint_or_404(task_type)
    module = _load_inspection_dataset_builder_module()
    manifest_path = _inspection_labeling_manifest_path(task_type)
    output_dir = _inspection_dataset_output_dir(task_type)
    try:
        return module.build_bundles(
            task_type=task_type,
            manifest_path=manifest_path,
            output_dir=output_dir,
            allow_suggestions=False,
        )
    except ValueError as exc:
        detail = str(exc)
        if "need at least 2 reviewed rows" in detail:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "inspection_state_dataset_not_enough_rows",
                "可用于导出训练数据的已确认状态样本还不够。",
                next_step="请先继续补状态标签，至少准备训练集和验证集的有效样本。",
                raw_detail=detail,
            )
        if "both train and validation rows are required" in detail:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "inspection_state_dataset_split_missing",
                "导出训练包时需要同时具备训练集和验证集样本。",
                next_step="请确认 manifest 里同时有 train 和 validation 两种切分后再导出。",
                raw_detail=detail,
            )
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_dataset_export_failed",
            "巡检状态训练包导出失败。",
            next_step="请检查状态标签、切分字段和图片路径后再重试。",
            raw_detail=detail,
        )


def _register_inspection_state_dataset_asset(
    *,
    task_type: str,
    task_label: str,
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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_state_dataset_bundle_not_found",
            "刚导出的巡检状态数据包文件不存在。",
            next_step="请重新执行一次导出训练数据，确认导出完成后再继续。",
        )
    if sensitivity_level not in {"L1", "L2", "L3"}:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "sensitivity_level_invalid",
            "敏感等级无效。",
            next_step="请把敏感等级改成 L1、L2 或 L3 之一。",
        )
    settings = get_settings()
    os.makedirs(settings.asset_repo_path, exist_ok=True)
    asset_id = str(uuid.uuid4())
    ext = source_bundle.suffix or ".zip"
    target_path = Path(settings.asset_repo_path) / f"{asset_id}{ext}"
    checksum, file_size = _copy_file_with_checksum(source_bundle, target_path)
    dataset_label = str(bundle_summary.get("dataset_label") or f"{task_type}-{asset_purpose}").strip()
    source_uri = f"vistral://training/inspection-state/{task_type}/export-dataset/{asset_purpose}"
    meta = {
        "size": file_size,
        "extension": ext,
        "asset_purpose": asset_purpose,
        "dataset_label": dataset_label,
        "use_case": use_case,
        "intended_model_code": intended_model_code,
        "task_type": task_type,
        "task_label": task_label,
        "label_sources": export_summary.get("label_sources") or {},
        "reviewer_counts": export_summary.get("reviewer_counts") or {},
        "generated_from": f"{task_type}_labeling_review",
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
                "generated_from": f"{task_type}_labeling_review",
            },
            request=request,
            actor=current_user,
        )
    version_summary = {
        "task_type": task_type,
        "task_label": task_label,
        "resource_count": bundle_summary.get("sample_count") or 0,
        "task_count": bundle_summary.get("sample_count") or 0,
        "reviewed_task_count": bundle_summary.get("sample_count") or 0,
        "label_vocab": list((_get_inspection_state_blueprint_or_404(task_type).get("label_values") or [])),
        "label_sources": export_summary.get("label_sources") or {},
        "reviewer_counts": export_summary.get("reviewer_counts") or {},
        "generated_from": f"{task_type}_labeling_review",
        "generated_at": export_summary.get("generated_at"),
        "accepted_rows": export_summary.get("accepted_rows"),
        "skipped_missing_label": export_summary.get("skipped_missing_label"),
    }
    dataset_version = create_dataset_version_record(
        db,
        asset=asset,
        dataset_label=dataset_label,
        dataset_key=str(bundle_summary.get("dataset_key") or dataset_label),
        asset_purpose=asset_purpose,
        source_type="inspection_state_export",
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
            "source_type": "inspection_state_export",
            "task_type": task_type,
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


def _export_inspection_state_assets_internal(
    *,
    task_type: str,
    payload: InspectionStateDatasetAssetImportRequest,
    request: Request,
    db: Session,
    current_user: AuthUser,
) -> dict[str, Any]:
    blueprint = _get_inspection_state_blueprint_or_404(task_type)
    export_summary = _export_inspection_state_dataset(task_type)
    intended_model_code = str(payload.intended_model_code or "").strip() or task_type
    use_case = str(payload.use_case or "").strip() or f"railcar-{task_type.replace('_', '-')}"
    train_bundle = export_summary.get("bundles", {}).get("train") or {}
    validation_bundle = export_summary.get("bundles", {}).get("validation") or {}
    train_asset = _register_inspection_state_dataset_asset(
        task_type=task_type,
        task_label=str(blueprint.get("label") or task_type),
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
    validation_asset = _register_inspection_state_dataset_asset(
        task_type=task_type,
        task_label=str(blueprint.get("label") or task_type),
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
        "task_type": task_type,
        "task_label": str(blueprint.get("label") or task_type),
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
        "is_synthetic": is_synthetic_training_job(job, base_model=base_model, candidate_model=candidate_model),
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


def _latest_job_for_target_model_code(db: Session, target_model_code: str) -> dict[str, Any] | None:
    job = (
        db.query(TrainingJob)
        .filter(TrainingJob.target_model_code == target_model_code)
        .order_by(TrainingJob.created_at.desc())
        .first()
    )
    return _serialize_job(db, job) if job else None


def _latest_model_for_task_type(db: Session, task_type: str) -> dict[str, Any] | None:
    model = (
        db.query(ModelRecord)
        .filter(ModelRecord.model_code == task_type)
        .order_by(ModelRecord.created_at.desc())
        .first()
    )
    if not model:
        return None
    return {
        **_model_summary(model),
        "status": model.status,
        "task_type": model.model_code,
        "created_at": model.created_at,
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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "training_job_not_found",
            "没有找到这条训练作业。",
            next_step="请回到训练中心刷新作业列表后，重新选择要操作的作业。",
        )
    if not job.assigned_worker_code or job.assigned_worker_code != worker_code:
        raise_ui_error(
            status.HTTP_403_FORBIDDEN,
            "training_job_worker_mismatch",
            "这条训练作业分配给了另一台训练机器。",
            next_step="请刷新训练机器状态后重新拉取作业，或在训练中心改派到当前机器。",
        )
    return job


def _control_note(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _ensure_retryable(job: TrainingJob, action_name: str) -> None:
    if job.candidate_model_id:
        raise_ui_error(
            status.HTTP_409_CONFLICT,
            "training_job_candidate_already_linked",
            "这条训练作业已经关联了待验证模型，不能继续当前操作。",
            next_step="请先查看当前待验证模型，或创建一条新的训练作业后再继续。",
            raw_detail={"action": action_name},
        )


def _resolve_target_worker(db: Session, worker_code: str | None, worker_host: str | None) -> tuple[TrainingWorker | None, str | None, str | None]:
    clean_code = _clean_optional(worker_code)
    clean_host = _clean_optional(worker_host)
    if not clean_code and not clean_host:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_target_worker_required",
            "改派训练作业前需要指定目标训练机器。",
            next_step="请填写训练机器编号或机器地址后再重试。",
        )

    target_worker = None
    if clean_code:
        target_worker = db.query(TrainingWorker).filter(TrainingWorker.worker_code == clean_code).first()
        if not target_worker:
            raise_ui_error(
                status.HTTP_404_NOT_FOUND,
                "training_target_worker_not_found",
                "没有找到目标训练机器。",
                next_step="请回到训练中心刷新训练机器列表后，重新选择目标机器。",
            )
        if target_worker.status != "ACTIVE":
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "training_target_worker_inactive",
                "目标训练机器当前不在线，不能直接改派。",
                next_step="请先让目标训练机器恢复在线，再重新改派作业。",
            )
        if clean_host and str(target_worker.host or "").strip().lower() != clean_host.lower():
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "training_target_worker_host_mismatch",
                "训练机器编号和机器地址不匹配。",
                next_step="请确认你填写的是同一台训练机器的编号和地址。",
            )
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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_validation_assets_overlap",
            "训练集和验证集不能引用同一条资源。",
            next_step="请把重复资源从训练集或验证集里移除后再创建作业。",
            raw_detail={"duplicate_asset_id": next(iter(duplicated))},
        )

    train_assets = _get_assets_or_400(db, train_asset_ids) if train_asset_ids else []
    validation_assets = _get_assets_or_400(db, validation_asset_ids) if validation_asset_ids else []
    # 关键约束：一次训练作业只能绑定同一个买家租户，避免跨租户数据混用。
    # Critical constraint: one training job must remain in a single buyer tenant scope.
    buyer_tenant_id = _ensure_single_buyer_scope([*train_assets, *validation_assets])
    if is_buyer_user(current_user.roles):
        if buyer_tenant_id and buyer_tenant_id != current_user.tenant_id:
            raise_ui_error(
                status.HTTP_403_FORBIDDEN,
                "buyer_training_cross_tenant_forbidden",
                "买方训练作业不能引用其他租户范围内的资源。",
                next_step="请只选择当前租户自己的训练/验证资源后再创建作业。",
            )
        buyer_tenant_id = current_user.tenant_id

    base_model = None
    owner_tenant_id = payload.owner_tenant_id
    if payload.base_model_id:
        base_model = db.query(ModelRecord).filter(ModelRecord.id == payload.base_model_id).first()
        if not base_model:
            raise_ui_error(
                status.HTTP_404_NOT_FOUND,
                "base_model_not_found",
                "基础模型不存在，当前作业无法继续创建。",
                next_step="请重新选择一版可见的基础模型，或改用默认基线。",
            )
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
                raise_ui_error(
                    status.HTTP_403_FORBIDDEN,
                    "base_model_not_released_to_buyer",
                    "当前基础模型还没有授权给当前买方租户。",
                    next_step="请先发布这版基础模型到当前买方，或改选已授权模型。",
                )
        if owner_tenant_id and base_model.owner_tenant_id and owner_tenant_id != base_model.owner_tenant_id:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "owner_tenant_mismatch_with_base_model",
                "目标归属租户和基础模型归属不一致。",
                next_step="请把归属租户改成和基础模型一致，或改选另一版基础模型。",
            )
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
    valid_final_text_rows = 0
    suggestion_rows = 0
    valid_suggestion_rows = 0
    for row in rows:
        status_key = str(row.get("review_status") or "pending").strip() or "pending"
        review_status_counts[status_key] = review_status_counts.get(status_key, 0) + 1
        if str(row.get("final_text") or "").strip():
            final_text_rows += 1
            if validate_car_number_text(row.get("final_text"))["valid"]:
                valid_final_text_rows += 1
        if str(row.get("ocr_suggestion") or "").strip():
            suggestion_rows += 1
            if validate_car_number_text(row.get("ocr_suggestion"))["valid"]:
                valid_suggestion_rows += 1
    summary_payload.update(
        {
            "annotated_rows": len(rows),
            "review_status_counts": review_status_counts,
            "final_text_rows": final_text_rows,
            "final_text_ratio": round((final_text_rows / len(rows)), 4) if rows else 0.0,
            "valid_final_text_rows": valid_final_text_rows,
            "suggestion_rows": suggestion_rows,
            "suggestion_ratio": round((suggestion_rows / len(rows)), 4) if rows else 0.0,
            "valid_suggestion_rows": valid_suggestion_rows,
            "car_number_rule": get_active_car_number_rule(),
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


@router.get("/inspection-workspaces/summary")
def get_inspection_workspace_summary(
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    blueprints = _load_inspection_dataset_blueprints()
    items: list[dict[str, Any]] = []
    for task_type, blueprint in blueprints.items():
        workspace_dir = _inspection_labeling_dir(task_type)
        rows = _load_inspection_labeling_rows(task_type)
        dataset_kind = str(blueprint.get("dataset_kind") or "").strip()
        completed_rows = 0
        needs_check_rows = 0
        pending_rows = 0
        split_counts: dict[str, int] = {}
        suggestion_rows = 0
        for row in rows:
            review_status = str(row.get("review_status") or "pending").strip() or "pending"
            if review_status == "needs_check":
                needs_check_rows += 1
            elif review_status == "done":
                completed_rows += 1
            else:
                pending_rows += 1
            if str(row.get("ocr_suggestion") or "").strip():
                suggestion_rows += 1
            split_key = str(row.get("split_hint") or "").strip() or "unassigned"
            split_counts[split_key] = split_counts.get(split_key, 0) + 1
        crop_ready_rows = sum(1 for row in rows if str(row.get("crop_file") or "").strip())
        if dataset_kind == "ocr_text":
            ready_rows = sum(1 for row in rows if str(row.get("final_text") or "").strip())
            starter_samples = _inspection_starter_samples(task_type, rows)
            proxy_replacement_samples = _inspection_proxy_replacement_samples(task_type, rows)
            readiness_blocker_rows = _inspection_readiness_blocker_rows(task_type)
            readiness_blocker_samples = _inspection_readiness_blocker_samples(task_type, rows)
            high_quality_suggestion_rows = _inspection_high_quality_suggestion_candidate_rows(task_type)
            manual_reviewed_rows = sum(
                1
                for row in rows
                if str(row.get("final_text") or "").strip()
                and str(row.get("reviewer") or "").strip()
                and str(row.get("reviewer") or "").strip() != "proxy_from_car_number_truth"
            )
            training_readiness = _inspection_ocr_training_readiness(task_type, rows)
            readiness_action_plan = _inspection_ocr_readiness_action_plan(task_type, rows, training_readiness)
        else:
            ready_rows = sum(1 for row in rows if str(row.get("label_value") or row.get("final_label") or "").strip())
            starter_samples = _inspection_state_starter_samples(task_type, rows)
            proxy_replacement_samples = []
            readiness_blocker_rows = []
            readiness_blocker_samples = []
            high_quality_suggestion_rows = []
            manual_reviewed_rows = ready_rows
            training_readiness = _inspection_state_training_readiness(task_type, rows)
            readiness_action_plan = {}

        dataset_dir = _inspection_dataset_output_dir(task_type)
        latest_dataset_summary = None
        summary_path = dataset_dir / f"{task_type}_dataset_summary.json"
        if summary_path.exists():
            try:
                latest_dataset_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                latest_dataset_summary = None

        items.append(
            {
                "task_type": task_type,
                "task_label": str(blueprint.get("label") or task_type),
                "dataset_kind": dataset_kind,
                "sample_target_min": int(blueprint.get("sample_target_min") or 0),
                "sample_target_recommended": int(blueprint.get("sample_target_recommended") or 0),
                "annotation_format": str(blueprint.get("annotation_format") or ""),
                "dataset_key_prefix": str(blueprint.get("dataset_key_prefix") or ""),
                "review_status_values": list(blueprint.get("review_status_values") or []),
                "label_values": list(blueprint.get("label_values") or []),
                "structured_fields": list(blueprint.get("structured_fields") or []),
                "capture_profile": blueprint.get("capture_profile") or {},
                "qa_targets": blueprint.get("qa_targets") or {},
                "notes": list(blueprint.get("notes") or []),
                "workspace_dir": _relative_repo_path(workspace_dir),
                "manifest_csv": _relative_repo_path(workspace_dir / "manifest.csv"),
                "summary_json": _relative_repo_path(workspace_dir / "summary.json"),
                "capture_plan_csv": _relative_repo_path(workspace_dir / "capture_plan.csv"),
                "dataset_output_dir": _relative_repo_path(dataset_dir),
                "row_count": len(rows),
                "crop_ready_rows": crop_ready_rows,
                "suggestion_rows": suggestion_rows,
                "ready_rows": ready_rows,
                "reviewed_rows": ready_rows,
                "manual_reviewed_rows": manual_reviewed_rows,
                "proxy_seeded_rows": sum(1 for row in rows if str(row.get("reviewer") or "").strip() == "proxy_from_car_number_truth"),
                "high_quality_review_candidate_rows": len(high_quality_suggestion_rows),
                "readiness_blocker_rows": len(readiness_blocker_rows),
                "ready_ratio": round((ready_rows / len(rows)), 4) if rows else 0.0,
                "completed_rows": completed_rows,
                "pending_rows": pending_rows,
                "needs_check_rows": needs_check_rows,
                "split_counts": split_counts,
                "latest_dataset_summary": latest_dataset_summary,
                "readiness_action_plan": readiness_action_plan,
                "bootstrap_command": (
                    f"python3 docker/scripts/bootstrap_inspection_labeling_workspace.py --task-type {task_type} "
                    "--output-dir demo_data/generated_datasets"
                ),
                "prepare_proxy_command": (
                    f"python3 docker/scripts/prepare_inspection_ocr_proxy_crops.py --task-type {task_type}"
                    if dataset_kind == "ocr_text"
                    else ""
                ),
                "generate_suggestions_command": (
                    f"python3 docker/scripts/generate_inspection_ocr_suggestions.py --task-type {task_type}"
                    if dataset_kind == "ocr_text"
                    else ""
                ),
                "build_command": (
                    f"python3 docker/scripts/build_inspection_task_dataset.py --task-type {task_type} "
                    f"--manifest demo_data/generated_datasets/{task_type}_labeling/manifest.csv "
                    f"--output-dir demo_data/generated_datasets/{task_type}_dataset"
                    + (" --allow-suggestions" if dataset_kind == "ocr_text" else "")
                ),
                "starter_samples": starter_samples,
                "proxy_replacement_samples": proxy_replacement_samples,
                "readiness_blocker_samples": readiness_blocker_samples,
                "training_readiness": training_readiness,
                "latest_training_job": _latest_job_for_target_model_code(db, task_type),
                "latest_candidate_model": _latest_model_for_task_type(db, task_type),
            }
        )
    return {
        "status": "ok",
        "workspace_count": len(items),
        "items": items,
    }


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
    final_text = str(payload.final_text or "").strip().upper()
    if final_text:
        validation = ensure_valid_car_number_text(final_text, field_name="final_text")
        row["final_text"] = validation["normalized_text"]
    else:
        row["final_text"] = ""
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


@router.get("/inspection-ocr/{task_type}/summary")
def get_inspection_ocr_labeling_summary(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    blueprint = _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    summary_payload = {}
    summary_path = _inspection_labeling_summary_path(task_type)
    if summary_path.exists():
        try:
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary_payload = {}
    review_status_counts: dict[str, int] = {}
    final_text_rows = 0
    suggestion_rows = 0
    crop_ready_rows = 0
    proxy_seeded_rows = 0
    manual_reviewed_rows = 0
    high_quality_suggestion_rows = 0
    for row in rows:
        status_key = str(row.get("review_status") or "pending").strip() or "pending"
        review_status_counts[status_key] = review_status_counts.get(status_key, 0) + 1
        if str(row.get("final_text") or "").strip():
            final_text_rows += 1
            reviewer = str(row.get("reviewer") or "").strip()
            if reviewer == "proxy_from_car_number_truth":
                proxy_seeded_rows += 1
            elif reviewer:
                manual_reviewed_rows += 1
        if str(row.get("ocr_suggestion") or "").strip():
            suggestion_rows += 1
            if float(row.get("ocr_suggestion_quality") or 0.0) >= 1.0:
                high_quality_suggestion_rows += 1
        if str(row.get("crop_file") or "").strip():
            crop_ready_rows += 1
    readiness = _inspection_ocr_training_readiness(task_type, rows)
    readiness_action_plan = _inspection_ocr_readiness_action_plan(task_type, rows, readiness)
    high_quality_suggestion_samples = _inspection_high_quality_suggestion_samples(task_type, rows)
    readiness_blocker_rows = _inspection_readiness_blocker_rows(task_type)
    readiness_blocker_samples = _inspection_readiness_blocker_samples(task_type, rows)
    summary_payload.update(
        {
            "task_type": task_type,
            "task_label": str(blueprint.get("label") or task_type),
            "annotated_rows": len(rows),
            "crop_ready_rows": crop_ready_rows,
            "review_status_counts": review_status_counts,
            "final_text_rows": final_text_rows,
            "final_text_ratio": round((final_text_rows / len(rows)), 4) if rows else 0.0,
            "suggestion_rows": suggestion_rows,
            "suggestion_ratio": round((suggestion_rows / len(rows)), 4) if rows else 0.0,
            "high_quality_suggestion_rows": high_quality_suggestion_rows,
            "high_quality_review_candidate_rows": int(readiness.get("high_quality_review_candidate_rows") or 0),
            "proxy_seeded_rows": proxy_seeded_rows,
            "manual_reviewed_rows": manual_reviewed_rows,
            "readiness_blocker_rows": len(readiness_blocker_rows),
            "structured_fields": list(blueprint.get("structured_fields") or []),
            "capture_profile": blueprint.get("capture_profile") or {},
            "qa_targets": blueprint.get("qa_targets") or {},
            "notes": list(blueprint.get("notes") or []),
            "starter_samples": _inspection_starter_samples(task_type, rows),
            "proxy_replacement_samples": _inspection_proxy_replacement_samples(task_type, rows),
            "high_quality_suggestion_samples": high_quality_suggestion_samples,
            "readiness_blocker_samples": readiness_blocker_samples,
            "training_readiness": readiness,
            "readiness_action_plan": readiness_action_plan,
        }
    )
    export_summary_path = _inspection_dataset_output_dir(task_type) / f"{task_type}_dataset_summary.json"
    if export_summary_path.exists():
        try:
            export_summary = json.loads(export_summary_path.read_text(encoding="utf-8"))
            summary_payload["latest_export"] = {
                "generated_at": export_summary.get("generated_at"),
                "accepted_rows": export_summary.get("accepted_rows"),
                "skipped_missing_label": export_summary.get("skipped_missing_label"),
                "label_sources": export_summary.get("label_sources") or {},
                "output_dir": export_summary.get("output_dir"),
                "bundles": export_summary.get("bundles") or {},
            }
        except json.JSONDecodeError:
            summary_payload["latest_export"] = None
    return summary_payload


@router.get("/inspection-ocr/{task_type}/items")
def list_inspection_ocr_labeling_items(
    task_type: str,
    q: str | None = Query(default=None, description="关键词搜索 / Search sample_id, source_file, suggestion, final_text"),
    review_status: str | None = Query(default=None, pattern=REVIEW_STATUS_PATTERN, description="复核状态 / pending|done|needs_check"),
    has_final_text: bool | None = Query(default=None, description="是否已有 final_text / Has reviewed text"),
    has_suggestion: bool | None = Query(default=None, description="是否有 OCR 建议 / Has OCR suggestion"),
    high_quality_suggestion: bool | None = Query(default=None, description="是否只看高质量建议 / Filter high-quality suggestion rows"),
    proxy_seeded: bool | None = Query(default=None, description="是否只看代理回灌真值 / Filter proxy-seeded rows"),
    readiness_blocker: bool | None = Query(default=None, description="是否只看当前阻断正式训练的样本 / Filter readiness blocker rows"),
    split_hint: str | None = Query(default=None, description="数据集切分 / train|validation"),
    limit: int = Query(default=80, ge=1, le=500, description="返回条数 / Max items"),
    offset: int = Query(default=0, ge=0, description="偏移量 / Offset"),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    token = str(q or "").strip().lower()
    filtered = []
    readiness_blocker_ids = {
        str(row.get("sample_id") or "").strip()
        for row in _inspection_readiness_blocker_rows(task_type)
    }
    for row in rows:
        item = _inspection_ocr_labeling_item_summary(task_type, row)
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
        if high_quality_suggestion is not None:
            item_high_quality = float(item.get("ocr_suggestion_quality") or 0.0) >= 1.0
            if item_high_quality != high_quality_suggestion:
                continue
        if proxy_seeded is not None and item["proxy_seeded"] != proxy_seeded:
            continue
        if readiness_blocker is not None:
            item_is_blocker = item["sample_id"] in readiness_blocker_ids
            if item_is_blocker != readiness_blocker:
                continue
        filtered.append(item)
    filtered.sort(key=_inspection_item_sort_key)
    total = len(filtered)
    page = filtered[offset: offset + limit]
    return {
        "task_type": task_type,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": page,
    }


@router.get("/inspection-ocr/{task_type}/items/{sample_id}/crop")
def get_inspection_ocr_labeling_crop(
    task_type: str,
    sample_id: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    matched = next((row for row in rows if str(row.get("sample_id") or "").strip() == sample_id), None)
    if not matched:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_ocr_sample_not_found",
            "没有找到这条巡检文字样本。",
            next_step="请回到样本列表重新选择，或刷新工作区后再试。",
        )
    crop_rel = str(matched.get("crop_file") or "").strip()
    if crop_rel:
        crop_path = _inspection_labeling_dir(task_type) / crop_rel
        if crop_path.exists() and crop_path.is_file():
            return FileResponse(crop_path)
    source_file = str(matched.get("source_file") or "").strip()
    if source_file:
        source_path = _resolve_image_path(matched, manifest_path=_inspection_labeling_manifest_path(task_type))
        if source_path and source_path.exists() and source_path.is_file():
            return FileResponse(source_path)
    raise_ui_error(
        status.HTTP_404_NOT_FOUND,
        "inspection_ocr_crop_not_found",
        "这条样本的裁剪图或原图不存在。",
        next_step="请重新生成代理裁剪，或检查 source_file / crop_file 路径是否有效。",
    )


@router.get("/inspection-ocr/{task_type}/items/{sample_id}/source")
def get_inspection_ocr_labeling_source(
    task_type: str,
    sample_id: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    matched = next((row for row in rows if str(row.get("sample_id") or "").strip() == sample_id), None)
    if not matched:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_ocr_sample_not_found",
            "没有找到这条巡检文字样本。",
            next_step="请回到样本列表重新选择，或刷新工作区后再试。",
        )
    source_path = _resolve_image_path({"source_file": matched.get("source_file")}, manifest_path=_inspection_labeling_manifest_path(task_type))
    if source_path and source_path.exists() and source_path.is_file():
        return FileResponse(source_path)
    raise_ui_error(
        status.HTTP_404_NOT_FOUND,
        "inspection_ocr_source_not_found",
        "这条样本的原始图片不存在。",
        next_step="请检查 source_file 路径，或重新生成这批巡检工作区样本。",
    )


@router.get("/inspection-state/{task_type}/summary")
def get_inspection_state_labeling_summary(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    blueprint = _get_inspection_state_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    summary_payload = {}
    summary_path = _inspection_labeling_summary_path(task_type)
    if summary_path.exists():
        try:
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary_payload = {}
    review_status_counts: dict[str, int] = {}
    label_counts: dict[str, int] = {}
    crop_ready_rows = 0
    reviewed_rows = 0
    for row in rows:
        status_key = str(row.get("review_status") or "pending").strip() or "pending"
        review_status_counts[status_key] = review_status_counts.get(status_key, 0) + 1
        label_value = str(row.get("label_value") or row.get("final_label") or row.get("label_class") or "").strip()
        if label_value:
            reviewed_rows += 1
            label_counts[label_value] = label_counts.get(label_value, 0) + 1
        if str(row.get("crop_file") or "").strip():
            crop_ready_rows += 1
    readiness = _inspection_state_training_readiness(task_type, rows)
    summary_payload.update(
        {
            "task_type": task_type,
            "task_label": str(blueprint.get("label") or task_type),
            "annotated_rows": len(rows),
            "crop_ready_rows": crop_ready_rows,
            "reviewed_rows": reviewed_rows,
            "reviewed_ratio": round((reviewed_rows / len(rows)), 4) if rows else 0.0,
            "review_status_counts": review_status_counts,
            "label_counts": label_counts,
            "label_values": list(blueprint.get("label_values") or []),
            "structured_fields": list(blueprint.get("structured_fields") or []),
            "capture_profile": blueprint.get("capture_profile") or {},
            "qa_targets": blueprint.get("qa_targets") or {},
            "notes": list(blueprint.get("notes") or []),
            "training_readiness": readiness,
            "starter_samples": _inspection_state_starter_samples(task_type, rows),
        }
    )
    export_summary_path = _inspection_dataset_output_dir(task_type) / f"{task_type}_dataset_summary.json"
    if export_summary_path.exists():
        try:
            export_summary = json.loads(export_summary_path.read_text(encoding="utf-8"))
            summary_payload["latest_export"] = {
                "generated_at": export_summary.get("generated_at"),
                "accepted_rows": export_summary.get("accepted_rows"),
                "skipped_missing_label": export_summary.get("skipped_missing_label"),
                "label_sources": export_summary.get("label_sources") or {},
                "output_dir": export_summary.get("output_dir"),
                "bundles": export_summary.get("bundles") or {},
            }
        except json.JSONDecodeError:
            summary_payload["latest_export"] = None
    return summary_payload


@router.get("/inspection-state/{task_type}/items")
def list_inspection_state_labeling_items(
    task_type: str,
    q: str | None = Query(default=None, description="关键词搜索 / Search sample_id, source_file, label_value"),
    review_status: str | None = Query(default=None, pattern=REVIEW_STATUS_PATTERN, description="复核状态 / pending|done|needs_check"),
    has_label_value: bool | None = Query(default=None, description="是否已有标签 / Has reviewed label"),
    label_value: str | None = Query(default=None, description="状态标签筛选 / Filter by state label"),
    split_hint: str | None = Query(default=None, description="数据集切分 / train|validation"),
    limit: int = Query(default=80, ge=1, le=500, description="返回条数 / Max items"),
    offset: int = Query(default=0, ge=0, description="偏移量 / Offset"),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_state_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    token = str(q or "").strip().lower()
    target_label = str(label_value or "").strip()
    filtered = []
    for row in rows:
        item = _inspection_state_labeling_item_summary(task_type, row)
        if token:
            searchable = " ".join(
                [
                    item["sample_id"],
                    item["source_file"],
                    item["label_class"],
                    item["label_value"],
                    item["notes"],
                ]
            ).lower()
            if token not in searchable:
                continue
        if review_status and item["review_status"] != review_status:
            continue
        if split_hint and item["split_hint"] != split_hint:
            continue
        if has_label_value is not None and item["has_label_value"] != has_label_value:
            continue
        if target_label and item["label_value"] != target_label:
            continue
        filtered.append(item)
    filtered.sort(key=_inspection_state_item_sort_key)
    total = len(filtered)
    page = filtered[offset: offset + limit]
    return {
        "task_type": task_type,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": page,
    }


@router.get("/inspection-state/{task_type}/items/{sample_id}/crop")
def get_inspection_state_labeling_crop(
    task_type: str,
    sample_id: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_state_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    matched = next((row for row in rows if str(row.get("sample_id") or "").strip() == sample_id), None)
    if not matched:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_state_sample_not_found",
            "没有找到这条巡检状态样本。",
            next_step="请回到样本列表重新选择，或刷新工作区后再试。",
        )
    crop_rel = str(matched.get("crop_file") or "").strip()
    if crop_rel:
        crop_path = _inspection_labeling_dir(task_type) / crop_rel
        if crop_path.exists() and crop_path.is_file():
            return FileResponse(crop_path)
    source_path = _resolve_image_path({"source_file": matched.get("source_file")}, manifest_path=_inspection_labeling_manifest_path(task_type))
    if source_path and source_path.exists() and source_path.is_file():
        return FileResponse(source_path)
    raise_ui_error(
        status.HTTP_404_NOT_FOUND,
        "inspection_state_crop_not_found",
        "这条样本的裁剪图或原图不存在。",
        next_step="请检查 source_file / crop_file 路径，或重新生成这批巡检状态工作区样本。",
    )


@router.get("/inspection-state/{task_type}/items/{sample_id}/source")
def get_inspection_state_labeling_source(
    task_type: str,
    sample_id: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_state_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    matched = next((row for row in rows if str(row.get("sample_id") or "").strip() == sample_id), None)
    if not matched:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_state_sample_not_found",
            "没有找到这条巡检状态样本。",
            next_step="请回到样本列表重新选择，或刷新工作区后再试。",
        )
    source_path = _resolve_image_path({"source_file": matched.get("source_file")}, manifest_path=_inspection_labeling_manifest_path(task_type))
    if source_path and source_path.exists() and source_path.is_file():
        return FileResponse(source_path)
    raise_ui_error(
        status.HTTP_404_NOT_FOUND,
        "inspection_state_source_not_found",
        "这条样本的原始图片不存在。",
        next_step="请检查 source_file 路径，或重新生成这批巡检状态工作区样本。",
    )


@router.post("/inspection-state/{task_type}/import-assets")
def import_inspection_state_assets(
    task_type: str,
    payload: InspectionStateImportAssetsRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
    db: Session = Depends(get_db),
):
    return _import_inspection_state_assets(
        task_type,
        asset_ids=payload.asset_ids,
        note=payload.note,
        db=db,
        current_user=current_user,
    )


@router.get("/inspection-state/{task_type}/export-review-queue")
def export_inspection_state_review_queue_csv(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_state_blueprint_or_404(task_type)
    rows = _inspection_state_review_candidate_rows(task_type)
    csv_text = _render_inspection_state_review_queue_csv(task_type, rows)
    filename = f"{task_type}_state_review_queue.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/inspection-state/{task_type}/export-review-pack")
def export_inspection_state_review_pack(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_state_blueprint_or_404(task_type)
    rows = _inspection_state_review_candidate_rows(task_type)
    archive = _build_inspection_state_review_pack(task_type, rows)
    filename = f"{task_type}_state_review_pack.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/inspection-state/{task_type}/preview-import-reviews")
async def preview_inspection_state_reviews_import(
    task_type: str,
    file: UploadFile = File(..., description="巡检状态复核 CSV / Inspection state review CSV"),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    _get_inspection_state_blueprint_or_404(task_type)
    filename = str(file.filename or "").strip().lower()
    if not filename.endswith(".csv"):
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_import_invalid_file",
            "导入文件必须是 CSV。",
            next_step="请先导出状态复核队列 CSV，再在表格里填写 label_value 后重新导入。",
        )
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_import_invalid_encoding",
            "导入 CSV 编码无法识别。",
            next_step="请使用 UTF-8 编码保存 CSV 后再导入。",
        )
    importer = str(current_user.username or current_user.id or "bulk_import_preview").strip()
    return _summarize_inspection_state_import(task_type, text=text, importer=importer, apply_updates=False)


@router.post("/inspection-state/{task_type}/import-reviews")
async def import_inspection_state_reviews(
    task_type: str,
    file: UploadFile = File(..., description="巡检状态复核 CSV / Inspection state review CSV"),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _get_inspection_state_blueprint_or_404(task_type)
    filename = str(file.filename or "").strip().lower()
    if not filename.endswith(".csv"):
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_import_invalid_file",
            "导入文件必须是 CSV。",
            next_step="请先导出状态复核队列 CSV，再在表格里填写 label_value 后重新导入。",
        )
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_import_invalid_encoding",
            "导入 CSV 编码无法识别。",
            next_step="请使用 UTF-8 编码保存 CSV 后再导入。",
        )
    importer = str(current_user.username or current_user.id or "bulk_import").strip()
    return _summarize_inspection_state_import(task_type, text=text, importer=importer, apply_updates=True)


@router.post("/inspection-state/{task_type}/items/{sample_id}/review")
def update_inspection_state_labeling_review(
    task_type: str,
    sample_id: str,
    payload: InspectionStateLabelingReviewRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    blueprint = _get_inspection_state_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    matched_index = next((idx for idx, row in enumerate(rows) if str(row.get("sample_id") or "").strip() == sample_id), None)
    if matched_index is None:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_state_sample_not_found",
            "没有找到这条巡检状态样本。",
            next_step="请回到样本列表重新选择，或刷新工作区后再试。",
        )
    normalized_label = str(payload.label_value or "").strip()
    if normalized_label and normalized_label not in list(blueprint.get("label_values") or []):
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_state_label_invalid",
            "这条状态标签不在当前任务允许的范围内。",
            next_step="请从页面提供的状态标签里重新选择一项后再保存。",
        )
    row = dict(rows[matched_index])
    row["label_value"] = normalized_label
    row["final_label"] = normalized_label
    row["review_status"] = payload.review_status
    row["reviewer"] = str(payload.reviewer or "").strip()
    row["notes"] = str(payload.notes or "").strip()
    rows[matched_index] = row
    _rewrite_inspection_labeling_files(task_type, rows)
    return {
        "status": "ok",
        "item": _inspection_state_labeling_item_summary(task_type, row),
    }


@router.post("/inspection-state/{task_type}/export-dataset")
def export_inspection_state_dataset(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    return _export_inspection_state_dataset(task_type)


@router.post("/inspection-state/{task_type}/export-assets")
def export_inspection_state_assets(
    task_type: str,
    payload: InspectionStateDatasetAssetImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    return _export_inspection_state_assets_internal(
        task_type=task_type,
        payload=payload,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/inspection-state/{task_type}/export-training-job")
def export_inspection_state_training_job(
    task_type: str,
    payload: InspectionStateTrainingJobCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    asset_result = _export_inspection_state_assets_internal(
        task_type=task_type,
        payload=payload,
        request=request,
        db=db,
        current_user=current_user,
    )
    intended_model_code = str(payload.intended_model_code or "").strip() or task_type
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
        spec=_default_inspection_state_training_spec(task_type, payload.spec),
    )
    job = create_training_job(create_payload, request=request, db=db, current_user=current_user)
    return {
        **asset_result,
        "job": job,
        "resolved_base_model": _model_summary(base_model),
        "resolved_spec": create_payload.spec,
    }


@router.get("/inspection-ocr/{task_type}/export-proxy-queue")
def export_inspection_proxy_queue_csv(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _inspection_proxy_seeded_rows(task_type)
    csv_text = _render_inspection_proxy_queue_csv(task_type, rows)
    filename = f"{task_type}_proxy_replacement_queue.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/inspection-ocr/{task_type}/export-review-pack")
def export_inspection_proxy_review_pack(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _inspection_proxy_seeded_rows(task_type)
    archive = _build_inspection_proxy_review_pack(task_type, rows)
    filename = f"{task_type}_proxy_review_pack.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/inspection-ocr/{task_type}/export-high-quality-queue")
def export_inspection_high_quality_queue_csv(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _inspection_high_quality_suggestion_candidate_rows(task_type)
    csv_text = _render_inspection_high_quality_queue_csv(task_type, rows)
    filename = f"{task_type}_high_quality_suggestion_queue.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/inspection-ocr/{task_type}/export-high-quality-pack")
def export_inspection_high_quality_review_pack(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _inspection_high_quality_suggestion_candidate_rows(task_type)
    archive = _build_inspection_high_quality_review_pack(task_type, rows)
    filename = f"{task_type}_high_quality_suggestion_pack.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/inspection-ocr/{task_type}/export-readiness-blocker-queue")
def export_inspection_readiness_blocker_queue_csv(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _inspection_readiness_blocker_rows(task_type)
    csv_text = _render_inspection_readiness_blocker_queue_csv(task_type, rows)
    filename = f"{task_type}_readiness_blocker_queue.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/inspection-ocr/{task_type}/export-readiness-blocker-pack")
def export_inspection_readiness_blocker_pack(
    task_type: str,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _inspection_readiness_blocker_rows(task_type)
    archive = _build_inspection_readiness_blocker_pack(task_type, rows)
    filename = f"{task_type}_readiness_blocker_pack.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/inspection-ocr/{task_type}/preview-import-reviews")
async def preview_inspection_ocr_reviews_import(
    task_type: str,
    file: UploadFile = File(..., description="巡检 OCR 复核 CSV / Inspection OCR review CSV"),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    filename = str(file.filename or "").strip().lower()
    if not filename.endswith(".csv"):
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_import_invalid_file",
            "导入文件必须是 CSV。",
            next_step="请先导出代理替换队列 CSV，再在表格里填写 final_text 后重新导入。",
        )
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_import_invalid_encoding",
            "导入 CSV 编码无法识别。",
            next_step="请使用 UTF-8 编码保存 CSV 后再导入。",
        )
    importer = str(current_user.username or current_user.id or "bulk_import_preview").strip()
    return _summarize_inspection_ocr_import(task_type, text=text, importer=importer, apply_updates=False)


@router.post("/inspection-ocr/{task_type}/import-reviews")
async def import_inspection_ocr_reviews(
    task_type: str,
    file: UploadFile = File(..., description="巡检 OCR 复核 CSV / Inspection OCR review CSV"),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _get_inspection_ocr_blueprint_or_404(task_type)
    filename = str(file.filename or "").strip().lower()
    if not filename.endswith(".csv"):
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_import_invalid_file",
            "导入文件必须是 CSV。",
            next_step="请先导出代理替换队列 CSV，再在表格里填写 final_text 后重新导入。",
        )
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "inspection_ocr_import_invalid_encoding",
            "导入 CSV 编码无法识别。",
            next_step="请使用 UTF-8 编码保存 CSV 后再导入。",
        )
    importer = str(current_user.username or current_user.id or "bulk_import").strip()
    return _summarize_inspection_ocr_import(task_type, text=text, importer=importer, apply_updates=True)


@router.post("/inspection-ocr/{task_type}/preview-accept-high-quality")
def preview_inspection_ocr_high_quality_accept(
    task_type: str,
    payload: InspectionOcrBulkAcceptHighQualityRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    reviewer = str(payload.reviewer or current_user.username or current_user.id or "bulk_accept_preview").strip()
    notes = str(payload.notes or "").strip()
    return _summarize_inspection_high_quality_accept(
        task_type,
        sample_ids=payload.sample_ids,
        limit=payload.limit,
        reviewer=reviewer,
        notes=notes,
        apply_updates=False,
    )


@router.post("/inspection-ocr/{task_type}/accept-high-quality")
def accept_inspection_ocr_high_quality(
    task_type: str,
    payload: InspectionOcrBulkAcceptHighQualityRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _get_inspection_ocr_blueprint_or_404(task_type)
    reviewer = str(payload.reviewer or current_user.username or current_user.id or "bulk_accept").strip()
    notes = str(payload.notes or "").strip()
    return _summarize_inspection_high_quality_accept(
        task_type,
        sample_ids=payload.sample_ids,
        limit=payload.limit,
        reviewer=reviewer,
        notes=notes,
        apply_updates=True,
    )


@router.post("/inspection-ocr/{task_type}/preview-confirm-proxy")
def preview_inspection_ocr_proxy_confirm(
    task_type: str,
    payload: InspectionOcrBulkConfirmProxyRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    reviewer = str(payload.reviewer or current_user.username or current_user.id or "proxy_confirm_preview").strip()
    notes = str(payload.notes or "").strip()
    return _summarize_inspection_proxy_confirm(
        task_type,
        sample_ids=payload.sample_ids,
        limit=payload.limit,
        reviewer=reviewer,
        notes=notes,
        apply_updates=False,
    )


@router.post("/inspection-ocr/{task_type}/confirm-proxy")
def confirm_inspection_ocr_proxy(
    task_type: str,
    payload: InspectionOcrBulkConfirmProxyRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _get_inspection_ocr_blueprint_or_404(task_type)
    reviewer = str(payload.reviewer or current_user.username or current_user.id or "proxy_confirm").strip()
    notes = str(payload.notes or "").strip()
    return _summarize_inspection_proxy_confirm(
        task_type,
        sample_ids=payload.sample_ids,
        limit=payload.limit,
        reviewer=reviewer,
        notes=notes,
        apply_updates=True,
    )


@router.post("/inspection-ocr/{task_type}/preview-resolve-readiness-blockers")
def preview_inspection_ocr_resolve_readiness_blockers(
    task_type: str,
    payload: InspectionOcrBulkResolveBlockerRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    reviewer = str(payload.reviewer or current_user.username or current_user.id or "readiness_blocker_preview").strip()
    notes = str(payload.notes or "").strip()
    return _summarize_inspection_readiness_blocker_resolution(
        task_type,
        sample_ids=payload.sample_ids,
        limit=payload.limit,
        reviewer=reviewer,
        notes=notes,
        apply_updates=False,
    )


@router.post("/inspection-ocr/{task_type}/resolve-readiness-blockers")
def resolve_inspection_ocr_readiness_blockers(
    task_type: str,
    payload: InspectionOcrBulkResolveBlockerRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _get_inspection_ocr_blueprint_or_404(task_type)
    reviewer = str(payload.reviewer or current_user.username or current_user.id or "readiness_blocker_resolve").strip()
    notes = str(payload.notes or "").strip()
    return _summarize_inspection_readiness_blocker_resolution(
        task_type,
        sample_ids=payload.sample_ids,
        limit=payload.limit,
        reviewer=reviewer,
        notes=notes,
        apply_updates=True,
    )


@router.post("/inspection-ocr/{task_type}/items/{sample_id}/review")
def update_inspection_ocr_labeling_review(
    task_type: str,
    sample_id: str,
    payload: InspectionOcrLabelingReviewRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    _get_inspection_ocr_blueprint_or_404(task_type)
    rows = _load_inspection_labeling_rows(task_type)
    matched_index = next((idx for idx, row in enumerate(rows) if str(row.get("sample_id") or "").strip() == sample_id), None)
    if matched_index is None:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "inspection_ocr_sample_not_found",
            "没有找到这条巡检文字样本。",
            next_step="请回到样本列表重新选择，或刷新工作区后再试。",
        )
    row = dict(rows[matched_index])
    row["final_text"] = str(payload.final_text or "").strip().upper()
    row["review_status"] = payload.review_status
    row["reviewer"] = str(payload.reviewer or "").strip()
    row["notes"] = str(payload.notes or "").strip()
    rows[matched_index] = row
    _rewrite_inspection_labeling_files(task_type, rows)
    return {
        "status": "ok",
        "item": _inspection_ocr_labeling_item_summary(task_type, row),
    }


@router.post("/inspection-ocr/{task_type}/export-dataset")
def export_inspection_ocr_dataset(
    task_type: str,
    payload: InspectionOcrDatasetExportRequest,
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    _ = current_user
    _ensure_inspection_proxy_seeded_allowed(task_type, allow_proxy_seeded=payload.allow_proxy_seeded)
    return _export_inspection_ocr_dataset(task_type, allow_suggestions=payload.allow_suggestions)


@router.post("/inspection-ocr/{task_type}/export-assets")
def export_inspection_ocr_assets(
    task_type: str,
    payload: InspectionOcrDatasetAssetImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    return _export_inspection_ocr_assets_internal(
        task_type=task_type,
        payload=payload,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/inspection-ocr/{task_type}/export-training-job")
def export_inspection_ocr_training_job(
    task_type: str,
    payload: InspectionOcrTrainingJobCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_CREATE_ROLES)),
):
    asset_result = _export_inspection_ocr_assets_internal(
        task_type=task_type,
        payload=payload,
        request=request,
        db=db,
        current_user=current_user,
    )
    intended_model_code = str(payload.intended_model_code or "").strip() or task_type
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
        spec=_default_inspection_ocr_training_spec(task_type, payload.spec),
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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_job_already_terminal",
            "这条训练作业已经结束，不能再取消。",
            next_step="请查看作业结果，或创建/重试新的训练作业。",
        )

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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_job_retry_status_invalid",
            "只有失败或已取消的训练作业才能重试。",
            next_step="请先选择状态为失败或已取消的作业，再执行重试。",
        )
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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_job_reassign_running_forbidden",
            "正在运行的训练作业不能直接改派。",
            next_step="请先取消当前作业，等它停下后再改派到其他训练机器。",
        )
    if job.status == TRAINING_JOB_STATUS_SUCCEEDED:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "training_job_reassign_succeeded_forbidden",
            "已经成功完成的训练作业不能改派。",
            next_step="请直接查看训练结果，或基于当前结果创建新的训练作业。",
        )
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


@router.post("/workers/cleanup")
def cleanup_training_workers(
    payload: TrainingWorkerCleanupRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_WORKER_ADMIN_ROLES)),
):
    reconcile_training_runtime_health(db)
    threshold_seconds = int(payload.stale_hours) * 3600
    now = datetime.utcnow()
    requested_worker_codes = {str(code or "").strip() for code in payload.worker_codes if str(code or "").strip()}
    active_worker_codes = {
        str(row.assigned_worker_code or "").strip()
        for row in db.query(TrainingJob).filter(~TrainingJob.status.in_(TRAINING_JOB_TERMINAL_STATUSES)).all()
        if str(row.assigned_worker_code or "").strip()
    }
    candidates: list[TrainingWorker] = []
    for worker in db.query(TrainingWorker).order_by(TrainingWorker.created_at.asc()).all():
        if worker.status == "ACTIVE":
            continue
        if worker.worker_code in active_worker_codes:
            continue
        if requested_worker_codes and worker.worker_code not in requested_worker_codes:
            continue
        reference_time = worker.last_seen_at or worker.created_at
        age_seconds = int((now - reference_time).total_seconds()) if reference_time else threshold_seconds + 1
        if not requested_worker_codes and age_seconds < threshold_seconds:
            continue
        candidates.append(worker)
        if len(candidates) >= int(payload.limit):
            break

    removed_rows = [
        {
            "id": worker.id,
            "worker_code": worker.worker_code,
            "status": worker.status,
            "host": worker.host,
            "last_seen_at": worker.last_seen_at,
            "created_at": worker.created_at,
        }
        for worker in candidates
    ]
    if not payload.dry_run:
        for worker in candidates:
            db.delete(worker)
        db.flush()

    record_audit(
        db,
        action=actions.TRAINING_WORKER_CLEANUP,
        resource_type="training_worker",
        resource_id=str(len(removed_rows)),
        detail={
            "stale_hours": payload.stale_hours,
            "worker_codes_requested": sorted(requested_worker_codes),
            "dry_run": payload.dry_run,
            "removed_count": len(removed_rows),
            "worker_codes": [row["worker_code"] for row in removed_rows],
            "note": _control_note(payload.note),
        },
        request=request,
        actor=current_user,
    )
    db.commit()
    return {
        "status": "ok",
        "dry_run": payload.dry_run,
        "stale_hours": payload.stale_hours,
        "worker_codes_requested": sorted(requested_worker_codes),
        "removed_count": len(removed_rows),
        "removed_workers": removed_rows,
    }


@router.post("/workers/heartbeat")
def training_worker_heartbeat(
    payload: TrainingWorkerHeartbeatRequest,
    request: Request,
    db: Session = Depends(get_db),
    worker_ctx: TrainingWorkerContext = Depends(get_training_worker),
):
    worker = db.query(TrainingWorker).filter(TrainingWorker.id == worker_ctx.id).first()
    if not worker:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "training_worker_not_found",
            "当前训练机器不存在，不能继续上报心跳。",
            next_step="请重新登记训练机器，或重新执行本机训练机器启动命令。",
        )

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

    resumable_rows = (
        db.query(TrainingJob)
        .filter(
            TrainingJob.status == TRAINING_JOB_STATUS_DISPATCHED,
            TrainingJob.assigned_worker_code == worker.worker_code,
            TrainingJob.started_at.is_(None),
        )
        .order_by(TrainingJob.created_at.asc())
        .all()
    )
    for row in resumable_rows:
        if len(jobs) >= payload.limit:
            break

        existing_summary = row.output_summary if isinstance(row.output_summary, dict) else {}
        row.output_summary = {
            **existing_summary,
            "last_resumed_at": datetime.utcnow().isoformat(),
            "last_resumed_worker_code": worker.worker_code,
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
