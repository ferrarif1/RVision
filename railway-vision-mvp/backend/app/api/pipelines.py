import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.constants import PIPELINE_STATUS_DRAFT
from app.core.constants import PIPELINE_STATUS_RELEASED
from app.db.database import get_db
from app.db.models import PipelineRecord
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import MODEL_READ_ROLES, MODEL_RELEASE_ROLES
from app.security.roles import is_buyer_user, is_platform_user, is_supplier_user
from app.services.audit_service import record_audit
from app.services.pipeline_service import collect_pipeline_model_ids
from app.services.pipeline_service import get_accessible_pipeline_or_404
from app.services.pipeline_service import get_pipeline_catalog
from app.services.pipeline_service import normalize_pipeline_config
from app.services.pipeline_service import pipeline_visible_to_user
from app.services.pipeline_service import serialize_pipeline
from app.services.pipeline_service import validate_pipeline_models

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class PipelineRegisterRequest(BaseModel):
    pipeline_code: str
    name: str
    version: str
    router_model_id: str | None = None
    expert_map: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    fusion_rules: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default=PIPELINE_STATUS_DRAFT)


class PipelineReleaseRequest(BaseModel):
    pipeline_id: str
    target_devices: list[str] = Field(default_factory=list)
    target_buyers: list[str] = Field(default_factory=list)
    traffic_ratio: int = Field(default=100, ge=1, le=100)
    release_notes: str | None = None


@router.get("")
def list_pipelines(
    device_code: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    query = db.query(PipelineRecord).order_by(PipelineRecord.created_at.desc())
    if is_platform_user(current_user.roles):
        rows = query.all()
    elif is_supplier_user(current_user.roles):
        rows = query.filter(PipelineRecord.owner_tenant_id == current_user.tenant_id).all()
    elif is_buyer_user(current_user.roles):
        rows = [row for row in query.all() if pipeline_visible_to_user(row, current_user, device_code=device_code)]
    else:
        rows = []

    payload = []
    for row in rows:
        catalog = get_pipeline_catalog(db, row)
        payload.append(serialize_pipeline(row, catalog.router, catalog.models))
    return payload


@router.get("/{pipeline_id}")
def get_pipeline(
    pipeline_id: str,
    device_code: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    pipeline = get_accessible_pipeline_or_404(db, current_user, pipeline_id, device_code=device_code)
    catalog = get_pipeline_catalog(db, pipeline)
    return serialize_pipeline(pipeline, catalog.router, catalog.models)


@router.post("/register")
def register_pipeline(
    payload: PipelineRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_RELEASE_ROLES)),
):
    existing = (
        db.query(PipelineRecord)
        .filter(PipelineRecord.pipeline_code == payload.pipeline_code, PipelineRecord.version == payload.version)
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline code+version already exists")

    normalized_config, expert_map, thresholds, fusion_rules = normalize_pipeline_config(
        router_model_id=payload.router_model_id,
        expert_map=payload.expert_map,
        thresholds=payload.thresholds,
        fusion_rules=payload.fusion_rules,
        config=payload.config,
    )
    model_ids = collect_pipeline_model_ids(normalized_config)
    if not model_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pipeline must reference at least one model")
    model_map = validate_pipeline_models(db, normalized_config, model_ids)

    pipeline = PipelineRecord(
        id=str(uuid.uuid4()),
        pipeline_code=payload.pipeline_code,
        name=payload.name,
        version=payload.version,
        router_model_id=(normalized_config.get("router") or {}).get("model_id"),
        expert_map=expert_map,
        thresholds=thresholds,
        fusion_rules=fusion_rules,
        config=normalized_config,
        status=PIPELINE_STATUS_DRAFT if payload.status != PIPELINE_STATUS_RELEASED else PIPELINE_STATUS_RELEASED,
        owner_tenant_id=current_user.tenant_id,
        created_by=current_user.id,
    )
    db.add(pipeline)
    db.commit()

    record_audit(
        db,
        action=actions.PIPELINE_REGISTER,
        resource_type="pipeline",
        resource_id=pipeline.id,
        detail={
            "pipeline_code": pipeline.pipeline_code,
            "version": pipeline.version,
            "router_model_id": pipeline.router_model_id,
            "model_ids": model_ids,
            "threshold_version": normalized_config.get("threshold_version"),
        },
        request=request,
        actor=current_user,
    )

    return serialize_pipeline(pipeline, model_map.get(pipeline.router_model_id) if pipeline.router_model_id else None, model_map)


@router.post("/release")
def release_pipeline(
    payload: PipelineReleaseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_RELEASE_ROLES)),
):
    pipeline = db.query(PipelineRecord).filter(PipelineRecord.id == payload.pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")

    config = dict(pipeline.config or {})
    config["release"] = {
        "target_devices": payload.target_devices,
        "target_buyers": payload.target_buyers,
        "traffic_ratio": payload.traffic_ratio,
        "release_notes": payload.release_notes,
    }
    pipeline.config = config
    pipeline.status = PIPELINE_STATUS_RELEASED
    db.add(pipeline)
    db.commit()

    record_audit(
        db,
        action=actions.PIPELINE_RELEASE,
        resource_type="pipeline",
        resource_id=pipeline.id,
        detail={
            "target_devices": payload.target_devices,
            "target_buyers": payload.target_buyers,
            "traffic_ratio": payload.traffic_ratio,
            "release_notes": payload.release_notes,
        },
        request=request,
        actor=current_user,
    )

    catalog = get_pipeline_catalog(db, pipeline)
    return serialize_pipeline(pipeline, catalog.router, catalog.models)
