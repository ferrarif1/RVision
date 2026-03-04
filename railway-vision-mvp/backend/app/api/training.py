import base64
import json
import os
import secrets
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.config import get_settings
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
from app.db.models import DataAsset, ModelRecord, Tenant, TrainingJob, TrainingWorker
from app.security.auth import hash_password
from app.security.dependencies import AuthUser, TrainingWorkerContext, get_training_worker, require_roles
from app.security.roles import (
    TRAINING_JOB_CREATE_ROLES,
    TRAINING_JOB_READ_ROLES,
    TRAINING_WORKER_ADMIN_ROLES,
    is_platform_user,
    is_supplier_user,
)
from app.services.audit_service import record_audit
from app.services.model_package_service import ModelPackageError, load_model_blobs, parse_and_validate_model_package, persist_model_package
from app.services.pipeline_service import normalize_model_inputs, normalize_model_outputs

router = APIRouter(prefix="/training", tags=["training"])

TRAINING_KIND_PATTERN = "^(train|finetune|evaluate)$"
WORKER_STATUS_PATTERN = "^(ACTIVE|INACTIVE|UNHEALTHY)$"
WORKER_UPDATE_STATUS_PATTERN = "^(RUNNING|SUCCEEDED|FAILED|CANCELLED)$"
MODEL_TYPE_PATTERN = "^(router|expert)$"


class TrainingJobCreateRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, min_length=1)
    validation_asset_ids: list[str] = Field(default_factory=list)
    base_model_id: str | None = None
    owner_tenant_id: str | None = None
    training_kind: str = Field(default="finetune", pattern=TRAINING_KIND_PATTERN)
    target_model_code: str
    target_version: str
    worker_selector: dict[str, Any] = Field(default_factory=dict)
    spec: dict[str, Any] = Field(default_factory=dict)


class TrainingWorkerRegisterRequest(BaseModel):
    worker_code: str
    name: str
    host: str | None = None
    status: str = Field(default="ACTIVE", pattern=WORKER_STATUS_PATTERN)
    labels: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)


class TrainingWorkerHeartbeatRequest(BaseModel):
    host: str | None = None
    status: str = Field(default="ACTIVE", pattern=WORKER_STATUS_PATTERN)
    labels: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)


class TrainingWorkerPullJobsRequest(BaseModel):
    limit: int = Field(default=1, ge=1, le=5)


class TrainingWorkerUpdateRequest(BaseModel):
    job_id: str
    status: str = Field(pattern=WORKER_UPDATE_STATUS_PATTERN)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class TrainingWorkerPullBaseModelRequest(BaseModel):
    job_id: str


def _job_visible_to_user(job: TrainingJob, current_user: AuthUser) -> bool:
    if is_platform_user(current_user.roles):
        return True
    if is_supplier_user(current_user.roles):
        return bool(current_user.tenant_id and job.owner_tenant_id == current_user.tenant_id)
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


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


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
    return {
        "id": job.id,
        "job_code": job.job_code,
        "status": job.status,
        "training_kind": job.training_kind,
        "target_model_code": job.target_model_code,
        "target_version": job.target_version,
        "asset_ids": job.asset_ids or [],
        "validation_asset_ids": job.validation_asset_ids or [],
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
        "dispatch_count": job.dispatch_count,
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
    train_assets = _get_assets_or_400(db, payload.asset_ids)
    validation_assets = _get_assets_or_400(db, payload.validation_asset_ids) if payload.validation_asset_ids else []
    buyer_tenant_id = _ensure_single_buyer_scope([*train_assets, *validation_assets])

    base_model = None
    owner_tenant_id = payload.owner_tenant_id
    if payload.base_model_id:
        base_model = db.query(ModelRecord).filter(ModelRecord.id == payload.base_model_id).first()
        if not base_model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Base model not found")
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
        asset_ids=payload.asset_ids,
        validation_asset_ids=payload.validation_asset_ids,
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
            "asset_ids": payload.asset_ids,
            "validation_asset_ids": payload.validation_asset_ids,
            "owner_tenant_id": owner_tenant_id,
            "buyer_tenant_id": buyer_tenant_id,
        },
        request=request,
        actor=current_user,
    )
    return _serialize_job(db, job)


@router.get("/jobs")
def list_training_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    training_kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    query = db.query(TrainingJob).order_by(TrainingJob.created_at.desc())
    if status_filter:
        query = query.filter(TrainingJob.status == status_filter)
    if training_kind:
        query = query.filter(TrainingJob.training_kind == training_kind)

    rows = query.all()
    visible = [row for row in rows if _job_visible_to_user(row, current_user)]
    return [_serialize_job(db, row) for row in visible]


@router.get("/jobs/{job_id}")
def get_training_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TRAINING_JOB_READ_ROLES)),
):
    job = _get_training_job_or_404(db, job_id, current_user)
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
    current_user: AuthUser = Depends(require_roles(*TRAINING_WORKER_ADMIN_ROLES)),
):
    rows = db.query(TrainingWorker).order_by(TrainingWorker.created_at.desc()).all()
    return [_serialize_worker(db, row) for row in rows]


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
    worker = db.query(TrainingWorker).filter(TrainingWorker.id == worker_ctx.id).first()
    if not worker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training worker not found")

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


@router.get("/workers/pull-asset")
def training_worker_pull_asset(
    job_id: str,
    asset_id: str,
    request: Request,
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
    job_id: str = Form(...),
    package: UploadFile = File(...),
    training_round: str = Form(default=""),
    dataset_label: str = Form(default=""),
    training_summary: str = Form(default=""),
    model_type: str = Form(default=MODEL_TYPE_EXPERT),
    runtime: str = Form(default=""),
    plugin_name: str = Form(default=""),
    inputs_json: str = Form(default=""),
    outputs_json: str = Form(default=""),
    gpu_mem_mb: str = Form(default=""),
    latency_ms: str = Form(default=""),
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
    if job.assigned_worker_code and job.assigned_worker_code != worker_ctx.code:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Training job assigned to a different worker")
    if job.status in TRAINING_JOB_TERMINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Training job already terminal")

    worker = db.query(TrainingWorker).filter(TrainingWorker.id == worker_ctx.id).first()
    if worker:
        worker.last_seen_at = datetime.utcnow()
        db.add(worker)

    existing_output_summary = job.output_summary if isinstance(job.output_summary, dict) else {}
    job.status = payload.status
    job.output_summary = {**existing_output_summary, **payload.output_summary}
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
