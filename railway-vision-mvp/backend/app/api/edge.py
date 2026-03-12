import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import TASK_STATUS_DISPATCHED
from app.core.constants import TASK_STATUS_FAILED
from app.core.constants import TASK_STATUS_PENDING
from app.core.constants import TASK_STATUS_SUCCEEDED
from app.core.config import get_settings
from app.core.ui_errors import raise_ui_error
from app.db.database import get_db
from app.db.models import DataAsset, InferenceResult, InferenceRun, InferenceTask, ModelRecord, ModelRelease, PipelineRecord, ReviewQueue
from app.security.dependencies import EdgeDeviceContext, get_edge_device
from app.services.audit_service import record_audit
from app.services.model_package_service import load_model_blobs
from app.services.pipeline_service import collect_pipeline_model_ids
from app.services.pipeline_service import get_pipeline_catalog
from app.services.pipeline_service import serialize_pipeline

router = APIRouter(prefix="/edge", tags=["edge"])

# If agent crashes after dispatch but before push_results, task would be stuck in DISPATCHED.
# Reclaim stale DISPATCHED tasks for re-delivery to improve demo robustness.
DISPATCH_RECLAIM_SECONDS = 90


class PullTasksRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=20, description="拉取任务数量 / Number of tasks requested by edge agent")


class PullModelRequest(BaseModel):
    model_id: str = Field(description="模型ID / Model ID to download")
    task_id: str | None = Field(default=None, description="任务ID / Optional task ID for task-scoped candidate model validation")


class EdgePushStatus(str, Enum):
    SUCCEEDED = TASK_STATUS_SUCCEEDED
    FAILED = TASK_STATUS_FAILED


class ResultItem(BaseModel):
    model_id: str | None = Field(default=None, description="模型ID / Model ID, optional for single-model tasks")
    model_hash: str = Field(description="模型哈希 / Model hash used for traceability")
    alert_level: str = Field(default="INFO", description="告警级别 / Alert level")
    result_json: dict = Field(default_factory=dict, description="推理结果JSON / Structured inference result payload")
    duration_ms: int | None = Field(default=None, description="耗时ms / Inference duration in milliseconds")
    screenshot_b64: str | None = Field(default=None, description="截图Base64 / Optional screenshot payload in base64")


class RunPayload(BaseModel):
    job_id: str | None = Field(default=None, description="运行批次ID / Runtime job ID from edge pipeline")
    pipeline_id: str | None = Field(default=None, description="流水线ID / Pipeline ID used in runtime")
    pipeline_version: str | None = Field(default=None, description="流水线版本 / Pipeline version")
    threshold_version: str | None = Field(default=None, description="阈值版本 / Threshold version")
    input_hash: str | None = Field(default=None, description="输入哈希 / Input hash for replay trace")
    input_summary: dict = Field(default_factory=dict, description="输入摘要 / Input summary metadata")
    models_versions: list[dict] = Field(default_factory=list, description="模型版本清单 / Executed model versions")
    timings: dict = Field(default_factory=dict, description="耗时明细 / Timing breakdown")
    result_summary: dict = Field(default_factory=dict, description="结果摘要 / Inference result summary")
    audit_hash: str | None = Field(default=None, description="审计哈希 / Optional precomputed audit hash")
    review_reasons: list[str] = Field(default_factory=list, description="人工复核原因 / Human-review enqueue reasons")


class PushResultsRequest(BaseModel):
    task_id: str = Field(description="任务ID / Task ID created by control plane")
    status: EdgePushStatus = Field(description="任务状态 / Final task status pushed by edge")
    error_message: str | None = Field(default=None, description="错误信息 / Optional error message when failed")
    items: list[ResultItem] = Field(default_factory=list, description="结果项列表 / Result items")
    run: RunPayload = Field(default_factory=RunPayload, description="运行元数据 / Runtime metadata payload")


def _is_model_released_to_device(db: Session, model_id: str, device_code: str) -> bool:
    releases = (
        db.query(ModelRelease)
        .filter(ModelRelease.model_id == model_id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .all()
    )
    for release in releases:
        targets = release.target_devices or []
        if not targets or device_code in targets:
            return True
    return False


def _is_model_authorized_for_task(db: Session, model_id: str, task_id: str | None, device_code: str) -> bool:
    clean_task_id = str(task_id or "").strip()
    if not clean_task_id:
        return False
    task = db.query(InferenceTask).filter(InferenceTask.id == clean_task_id).first()
    if not task:
        return False
    if task.model_id != model_id:
        return False
    if task.device_code and task.device_code != device_code:
        return False
    return task.status in {TASK_STATUS_PENDING, TASK_STATUS_DISPATCHED}


def _normalize_pipeline_id(pipeline_id: str | None) -> str | None:
    cleaned = str(pipeline_id or "").strip()
    if not cleaned:
        return None
    if len(cleaned) <= 36:
        return cleaned
    tail = cleaned[-36:]
    try:
        uuid.UUID(tail)
        return tail
    except ValueError:
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:36]


def _resolve_run_pipeline_id(db: Session, pipeline_id: str | None) -> str | None:
    candidate = _normalize_pipeline_id(pipeline_id)
    if not candidate:
        return None
    exists = db.query(PipelineRecord.id).filter(PipelineRecord.id == candidate).first()
    return candidate if exists else None


@router.get("/ping")
def edge_ping(device: EdgeDeviceContext = Depends(get_edge_device)):
    return {"status": "ok", "device_code": device.code, "timestamp": datetime.utcnow()}


@router.post("/pull_tasks")
def edge_pull_tasks(
    payload: PullTasksRequest,
    request: Request,
    db: Session = Depends(get_db),
    device: EdgeDeviceContext = Depends(get_edge_device),
):
    # 把长时间未完成的 DISPATCHED 任务回收到可再次派发状态，避免 Agent 异常后任务卡死。
    # Reclaim stale DISPATCHED tasks to prevent stuck tasks after agent crash/restart.
    stale_before = datetime.utcnow() - timedelta(seconds=DISPATCH_RECLAIM_SECONDS)
    query = (
        db.query(InferenceTask)
        .filter(
            or_(
                InferenceTask.status == TASK_STATUS_PENDING,
                and_(
                    InferenceTask.status == TASK_STATUS_DISPATCHED,
                    InferenceTask.finished_at.is_(None),
                    InferenceTask.started_at.is_not(None),
                    InferenceTask.started_at < stale_before,
                ),
            )
        )
        .filter((InferenceTask.device_code == device.code) | (InferenceTask.device_code.is_(None)))
        .order_by(InferenceTask.created_at.asc())
    )
    requested_limit = min(payload.limit, 20)
    # Read deeper than the requested limit so invalid stale rows do not block later valid tasks.
    tasks = query.limit(max(requested_limit * 5, 50)).all()

    result = []
    reclaimed = 0
    invalid = 0
    for task in tasks:
        if len(result) >= requested_limit:
            break
        asset = db.query(DataAsset).filter(DataAsset.id == task.asset_id).first()
        model = db.query(ModelRecord).filter(ModelRecord.id == task.model_id).first()
        if not asset or not model:
            task.status = TASK_STATUS_FAILED
            task.finished_at = datetime.utcnow()
            task.error_message = "Task asset or model missing during edge dispatch"
            invalid += 1
            continue

        if task.status == TASK_STATUS_DISPATCHED:
            reclaimed += 1
        task.status = TASK_STATUS_DISPATCHED
        task.dispatch_count += 1
        task.started_at = datetime.utcnow()

        pipeline_payload = None
        model_registry: dict[str, dict] = {}
        if task.pipeline_id:
            pipeline = db.query(PipelineRecord).filter(PipelineRecord.id == task.pipeline_id).first()
            if pipeline:
                catalog = get_pipeline_catalog(db, pipeline)
                pipeline_payload = serialize_pipeline(pipeline, catalog.router, catalog.models)
                model_registry = {item["id"]: item for item in pipeline_payload.get("models", [])}

        if not model_registry and model:
            model_registry[model.id] = {
                "id": model.id,
                "model_code": model.model_code,
                "version": model.version,
                "model_hash": model.model_hash,
                "task_type": (model.manifest or {}).get("task_type"),
                "model_type": model.model_type,
                "runtime": model.runtime,
                "plugin_name": model.plugin_name,
                "inputs": model.inputs,
                "outputs": model.outputs,
            }

        result.append(
            {
                "task_id": task.id,
                "task_type": task.task_type,
                "policy": task.policy,
                "pipeline_id": task.pipeline_id,
                "device_code": device.code,
                "buyer_tenant_id": task.buyer_tenant_id,
                "pipeline": pipeline_payload,
                "models": model_registry,
                "model": {
                    "id": model.id,
                    "model_code": model.model_code,
                    "version": model.version,
                    "model_hash": model.model_hash,
                }
                if model
                else None,
                "asset": {
                    "id": asset.id,
                    "file_name": asset.file_name,
                    "asset_type": asset.asset_type,
                    "sensitivity_level": asset.sensitivity_level,
                    "meta": asset.meta if isinstance(asset.meta, dict) else {},
                },
            }
        )

    db.commit()

    record_audit(
        db,
        action=actions.EDGE_PULL_TASKS,
        resource_type="edge_task_pull",
        resource_id=device.code,
        detail={"count": len(result), "reclaimed_dispatched_count": reclaimed, "invalid_task_count": invalid},
        request=request,
        actor_role="edge-agent",
    )

    return {"device_code": device.code, "tasks": result}


@router.post("/pull_model")
def edge_pull_model(
    payload: PullModelRequest,
    request: Request,
    db: Session = Depends(get_db),
    device: EdgeDeviceContext = Depends(get_edge_device),
):
    model = db.query(ModelRecord).filter(ModelRecord.id == payload.model_id).first()
    if not model:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "model_not_found",
            "模型不存在，边缘端当前无法拉取这版模型。",
            next_step="请在平台侧确认模型记录仍存在，再重新派发或重新拉取模型。",
        )

    if not _is_model_released_to_device(db, model.id, device.code) and not _is_model_authorized_for_task(
        db,
        model_id=model.id,
        task_id=payload.task_id,
        device_code=device.code,
    ):
        raise_ui_error(
            status.HTTP_403_FORBIDDEN,
            "model_not_released_to_device",
            "这版模型还没有授权到当前设备，边缘端不能直接拉取。",
            next_step="请先发布到当前设备，或通过任务级授权重新派发验证任务。",
        )

    if not (os.path.exists(model.manifest_uri) and os.path.exists(model.encrypted_uri) and os.path.exists(model.signature_uri)):
        raise_ui_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "model_artifacts_missing",
            "模型记录存在，但模型文件不完整，边缘端暂时无法加载。",
            next_step="请重新发布这版模型，或在平台侧重新生成并回收模型产物。",
        )

    blobs = load_model_blobs(model.manifest_uri, model.encrypted_uri, model.signature_uri)

    record_audit(
        db,
        action=actions.MODEL_DOWNLOAD,
        resource_type="model",
        resource_id=model.id,
        detail={"device_code": device.code},
        request=request,
        actor_role="edge-agent",
    )
    record_audit(
        db,
        action=actions.EDGE_PULL_MODEL,
        resource_type="edge_model_pull",
        resource_id=model.id,
        detail={"device_code": device.code},
        request=request,
        actor_role="edge-agent",
    )

    return {
        "model_id": model.id,
        "model_code": model.model_code,
        "version": model.version,
        "model_hash": model.model_hash,
        "manifest_b64": blobs["manifest_b64"],
        "model_enc_b64": blobs["model_enc_b64"],
        "signature_b64": blobs["signature_b64"],
    }


@router.get("/pull_asset")
def edge_pull_asset(
    asset_id: str = Query(..., description="资产ID / Asset ID requested by edge"),
    db: Session = Depends(get_db),
    device: EdgeDeviceContext = Depends(get_edge_device),
):
    asset = db.query(DataAsset).filter(DataAsset.id == asset_id).first()
    if not asset:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "edge_asset_not_found",
            "边缘设备请求的资产不存在。",
            next_step="请确认资产编号是否正确，或重新下发一个有效任务。",
        )

    if not os.path.exists(asset.storage_uri):
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "edge_asset_file_missing",
            "边缘设备请求的资产文件不存在。",
            next_step="请重新上传资产，或让控制面重新分配有效资产。",
        )

    with open(asset.storage_uri, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    return {
        "asset_id": asset.id,
        "file_name": asset.file_name,
        "asset_type": asset.asset_type,
        "sensitivity_level": asset.sensitivity_level,
        "file_b64": b64,
        "device_code": device.code,
    }


@router.post("/push_results")
def edge_push_results(
    payload: PushResultsRequest,
    request: Request,
    db: Session = Depends(get_db),
    device: EdgeDeviceContext = Depends(get_edge_device),
):
    task = db.query(InferenceTask).filter(InferenceTask.id == payload.task_id).first()
    if not task:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "edge_task_not_found",
            "边缘设备回传结果对应的任务不存在。",
            next_step="请确认边缘设备使用的是最新任务，或重新拉取任务后再回传。",
        )
    # Idempotency: tolerate edge retries after control-plane has already finalized the task.
    if task.finished_at and task.status in {TASK_STATUS_SUCCEEDED, TASK_STATUS_FAILED} and task.status == payload.status.value:
        return {"task_id": task.id, "status": task.status, "saved_results": 0, "idempotent": True}

    model = db.query(ModelRecord).filter(ModelRecord.id == task.model_id).first()
    if not model:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "edge_task_model_not_found",
            "边缘设备执行任务时对应的模型不存在。",
            next_step="请重新下发模型或重新创建任务后再执行。",
        )

    settings = get_settings()
    screenshot_dir = os.path.join(settings.asset_repo_path, "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    for item in payload.items:
        screenshot_uri = None
        # L2 截图仅在策略允许时落盘并入库，避免默认扩大数据回传范围。
        # Persist screenshot only when policy allows frame upload.
        if item.screenshot_b64 and task.policy.get("upload_frames", True):
            screenshot_id = str(uuid.uuid4())
            screenshot_path = os.path.join(screenshot_dir, f"{screenshot_id}.jpg")
            with open(screenshot_path, "wb") as f:
                f.write(base64.b64decode(item.screenshot_b64))
            screenshot_uri = screenshot_path

            db.add(
                DataAsset(
                    id=screenshot_id,
                    file_name=f"{screenshot_id}.jpg",
                    asset_type="screenshot",
                    storage_uri=screenshot_path,
                    source_uri=None,
                    sensitivity_level="L2",
                    checksum=model.model_hash,
                    buyer_tenant_id=task.buyer_tenant_id,
                    meta={"from_task": task.id, "device_code": device.code},
                    uploaded_by=task.created_by,
                )
            )

        db.add(
            InferenceResult(
                id=str(uuid.uuid4()),
                task_id=task.id,
                model_id=item.model_id or model.id,
                model_hash=item.model_hash,
                result_json=item.result_json,
                buyer_tenant_id=task.buyer_tenant_id,
                alert_level=item.alert_level,
                screenshot_uri=screenshot_uri,
                duration_ms=item.duration_ms,
            )
        )

    task.status = payload.status.value
    task.error_message = payload.error_message
    task.finished_at = datetime.utcnow()
    db.add(task)

    if payload.run.job_id or payload.run.input_hash or payload.run.result_summary:
        raw_pipeline_id = payload.run.pipeline_id or task.pipeline_id
        run_pipeline_id = _resolve_run_pipeline_id(db, raw_pipeline_id)
        run_job_id = payload.run.job_id or task.id
        input_hash = payload.run.input_hash or hashlib.sha256(f"{task.asset_id}:{task.id}".encode("utf-8")).hexdigest()
        audit_hash_source = {
            "task_id": task.id,
            "pipeline_id": run_pipeline_id,
            "pipeline_id_raw": raw_pipeline_id,
            "pipeline_version": payload.run.pipeline_version,
            "threshold_version": payload.run.threshold_version,
            "input_hash": input_hash,
            "models_versions": payload.run.models_versions,
            "timings": payload.run.timings,
            "result_summary": payload.run.result_summary,
        }
        audit_hash = payload.run.audit_hash or hashlib.sha256(json.dumps(audit_hash_source, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        existing_run = db.query(InferenceRun).filter(InferenceRun.job_id == run_job_id).first()
        if existing_run:
            existing_run.task_id = task.id
            existing_run.pipeline_id = run_pipeline_id
            existing_run.pipeline_version = payload.run.pipeline_version
            existing_run.threshold_version = payload.run.threshold_version
            existing_run.input_hash = input_hash
            existing_run.input_summary = payload.run.input_summary
            existing_run.models_versions = payload.run.models_versions
            existing_run.timings = payload.run.timings
            existing_run.result_summary = payload.run.result_summary
            existing_run.audit_hash = audit_hash
            existing_run.status = payload.status.value
            db.add(existing_run)
        else:
            db.add(
                InferenceRun(
                    id=str(uuid.uuid4()),
                    job_id=run_job_id,
                    task_id=task.id,
                    pipeline_id=run_pipeline_id,
                    pipeline_version=payload.run.pipeline_version,
                    threshold_version=payload.run.threshold_version,
                    input_hash=input_hash,
                    input_summary=payload.run.input_summary,
                    models_versions=payload.run.models_versions,
                    timings=payload.run.timings,
                    result_summary=payload.run.result_summary,
                    audit_hash=audit_hash,
                    status=payload.status.value,
                )
            )
        record_audit(
            db,
            action=actions.ORCHESTRATOR_RUN,
            resource_type="inference_run",
            resource_id=run_job_id,
            detail={
                "pipeline_id": run_pipeline_id,
                "pipeline_id_raw": raw_pipeline_id,
                "pipeline_version": payload.run.pipeline_version,
                "threshold_version": payload.run.threshold_version,
                "input_hash": input_hash,
                "audit_hash": audit_hash,
                "result_summary": payload.run.result_summary,
            },
            request=request,
            actor_role="edge-agent",
        )
        for reason in payload.run.review_reasons:
            review = ReviewQueue(
                id=str(uuid.uuid4()),
                job_id=run_job_id,
                task_id=task.id,
                pipeline_id=run_pipeline_id,
                reason=reason,
                assigned_to=None,
                label_result=None,
                status="PENDING",
            )
            db.add(review)
            record_audit(
                db,
                action=actions.REVIEW_QUEUE_ENQUEUE,
                resource_type="review_queue",
                resource_id=review.id,
                detail={"task_id": task.id, "reason": reason},
                request=request,
                actor_role="edge-agent",
            )

    db.commit()

    record_audit(
        db,
        action=actions.EDGE_PUSH_RESULTS,
        resource_type="edge_result_push",
        resource_id=task.id,
        detail={"device_code": device.code, "status": payload.status.value, "count": len(payload.items)},
        request=request,
        actor_role="edge-agent",
    )

    return {"task_id": task.id, "status": task.status, "saved_results": len(payload.items)}
