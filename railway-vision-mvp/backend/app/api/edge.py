import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    limit: int = 5


class PullModelRequest(BaseModel):
    model_id: str


class EdgePushStatus(str, Enum):
    SUCCEEDED = TASK_STATUS_SUCCEEDED
    FAILED = TASK_STATUS_FAILED


class ResultItem(BaseModel):
    model_id: str | None = None
    model_hash: str
    alert_level: str = "INFO"
    result_json: dict = Field(default_factory=dict)
    duration_ms: int | None = None
    screenshot_b64: str | None = None


class RunPayload(BaseModel):
    job_id: str | None = None
    pipeline_id: str | None = None
    pipeline_version: str | None = None
    threshold_version: str | None = None
    input_hash: str | None = None
    input_summary: dict = Field(default_factory=dict)
    models_versions: list[dict] = Field(default_factory=list)
    timings: dict = Field(default_factory=dict)
    result_summary: dict = Field(default_factory=dict)
    audit_hash: str | None = None
    review_reasons: list[str] = Field(default_factory=list)


class PushResultsRequest(BaseModel):
    task_id: str
    status: EdgePushStatus
    error_message: str | None = None
    items: list[ResultItem] = Field(default_factory=list)
    run: RunPayload = Field(default_factory=RunPayload)


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
    tasks = query.limit(min(payload.limit, 20)).all()

    result = []
    reclaimed = 0
    for task in tasks:
        asset = db.query(DataAsset).filter(DataAsset.id == task.asset_id).first()
        model = db.query(ModelRecord).filter(ModelRecord.id == task.model_id).first()
        if not asset or not model:
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
        detail={"count": len(result), "reclaimed_dispatched_count": reclaimed},
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    if not _is_model_released_to_device(db, model.id, device.code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Model not released to this device")

    if not (os.path.exists(model.manifest_uri) and os.path.exists(model.encrypted_uri) and os.path.exists(model.signature_uri)):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Model artifacts missing")

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
    asset_id: str,
    db: Session = Depends(get_db),
    device: EdgeDeviceContext = Depends(get_edge_device),
):
    asset = db.query(DataAsset).filter(DataAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if not os.path.exists(asset.storage_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file missing")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    model = db.query(ModelRecord).filter(ModelRecord.id == task.model_id).first()
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task model not found")

    settings = get_settings()
    screenshot_dir = os.path.join(settings.asset_repo_path, "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    for item in payload.items:
        screenshot_uri = None
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
        input_hash = payload.run.input_hash or hashlib.sha256(f"{task.asset_id}:{task.id}".encode("utf-8")).hexdigest()
        audit_hash_source = {
            "task_id": task.id,
            "pipeline_id": payload.run.pipeline_id or task.pipeline_id,
            "pipeline_version": payload.run.pipeline_version,
            "threshold_version": payload.run.threshold_version,
            "input_hash": input_hash,
            "models_versions": payload.run.models_versions,
            "timings": payload.run.timings,
            "result_summary": payload.run.result_summary,
        }
        audit_hash = payload.run.audit_hash or hashlib.sha256(json.dumps(audit_hash_source, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        db.add(
            InferenceRun(
                id=str(uuid.uuid4()),
                job_id=payload.run.job_id or task.id,
                task_id=task.id,
                pipeline_id=payload.run.pipeline_id or task.pipeline_id,
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
            resource_id=payload.run.job_id or task.id,
            detail={
                "pipeline_id": payload.run.pipeline_id or task.pipeline_id,
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
                job_id=payload.run.job_id or task.id,
                task_id=task.id,
                pipeline_id=payload.run.pipeline_id or task.pipeline_id,
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
