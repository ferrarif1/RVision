import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.constants import PIPELINE_STATUS_DRAFT
from app.core.constants import PIPELINE_STATUS_RELEASED
from app.db.database import get_db
from app.db.models import Device, PipelineRecord, Tenant
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
    pipeline_code: str = Field(description="流水线编码 / Unique pipeline code")
    name: str = Field(description="流水线名称 / Human-readable pipeline name")
    version: str = Field(description="流水线版本 / Pipeline version")
    router_model_id: str | None = Field(default=None, description="路由模型ID / Router model ID")
    expert_map: dict[str, Any] = Field(default_factory=dict, description="专家映射 / Task-to-expert model mapping")
    thresholds: dict[str, Any] = Field(default_factory=dict, description="阈值配置 / Threshold configuration")
    fusion_rules: dict[str, Any] = Field(default_factory=dict, description="融合规则 / Fusion rules for multi-model outputs")
    config: dict[str, Any] = Field(default_factory=dict, description="完整配置对象 / Full pipeline config object")
    status: str = Field(default=PIPELINE_STATUS_DRAFT, description="流水线状态 / Pipeline status")


class PipelineReleaseRequest(BaseModel):
    pipeline_id: str = Field(description="流水线ID / Pipeline record ID to release")
    target_devices: list[str] = Field(default_factory=list, description="目标设备列表 / Target edge device codes")
    target_buyers: list[str] = Field(default_factory=list, description="目标买家列表 / Target buyer tenant codes")
    traffic_ratio: int = Field(default=100, ge=1, le=100, description="流量比例 / Traffic ratio percentage")
    release_notes: str | None = Field(default=None, description="发布说明 / Release notes")


@router.get("/{pipeline_id}/release-workbench")
def get_pipeline_release_workbench(
    pipeline_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_RELEASE_ROLES)),
):
    pipeline = get_accessible_pipeline_or_404(db, current_user, pipeline_id)
    catalog = get_pipeline_catalog(db, pipeline)
    devices = (
        db.query(Device)
        .filter(Device.status == "ACTIVE")
        .order_by(Device.last_seen_at.desc().nullslast(), Device.created_at.desc())
        .limit(20)
        .all()
    )
    buyers = (
        db.query(Tenant)
        .filter(Tenant.tenant_type == "BUYER", Tenant.status == "ACTIVE")
        .order_by(Tenant.created_at.desc())
        .limit(20)
        .all()
    )
    release_config = (pipeline.config or {}).get("release") if isinstance(pipeline.config, dict) else {}
    recommended_devices = list(release_config.get("target_devices") or [])
    recommended_buyers = list(release_config.get("target_buyers") or [])
    if not recommended_devices and devices:
        recommended_devices = [devices[0].code]
    if not recommended_buyers and buyers:
        recommended_buyers = [buyers[0].tenant_code]
    return {
        "pipeline": serialize_pipeline(pipeline, catalog.router, catalog.models),
        "scope_candidates": {
            "devices": [
                {"code": row.code, "name": row.name, "status": row.status, "last_seen_at": row.last_seen_at}
                for row in devices
            ],
            "buyers": [
                {"tenant_code": row.tenant_code, "name": row.name, "status": row.status}
                for row in buyers
            ],
        },
        "recommended_release": {
            "target_devices": recommended_devices,
            "target_buyers": recommended_buyers,
            "traffic_ratio": int(release_config.get("traffic_ratio") or 100),
            "release_notes": str(release_config.get("release_notes") or "").strip() or "console release",
        },
    }


@router.get("")
def list_pipelines(
    device_code: str | None = Query(default=None, description="设备编码 / Optional device code for visibility filtering"),
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
    device_code: str | None = Query(default=None, description="设备编码 / Optional device code for release-scope filtering"),
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
    # 核心约束：注册时即校验模型存在性与可见性，避免运行时才发现配置失效。
    # Validate referenced model IDs at register-time to fail fast.
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
