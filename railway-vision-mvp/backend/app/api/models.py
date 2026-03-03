import json
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import MODEL_TYPE_EXPERT
from app.core.constants import MODEL_TYPE_ROUTER
from app.core.constants import MODEL_STATUS_APPROVED
from app.core.constants import MODEL_STATUS_RELEASED
from app.core.constants import MODEL_STATUS_SUBMITTED
from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import AuditLog, ModelRecord, ModelRelease, User
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import (
    MODEL_APPROVE_ROLES,
    MODEL_READ_ROLES,
    MODEL_RELEASE_ROLES,
    MODEL_SUBMIT_ROLES,
    ROLE_SUPPLIER_ENGINEER,
    expand_roles,
    is_buyer_user,
    is_platform_user,
    is_supplier_user,
)
from app.services.audit_service import record_audit
from app.services.model_package_service import (
    ModelPackageError,
    parse_and_validate_model_package,
    persist_model_package,
)
from app.services.pipeline_service import build_model_registry_payload
from app.services.pipeline_service import normalize_model_inputs
from app.services.pipeline_service import normalize_model_outputs

router = APIRouter(prefix="/models", tags=["models"])
MODEL_SOURCE_PATTERN = "^(initial_algorithm|pretrained_seed|finetuned_candidate|delivery_candidate)$"
DELIVERY_MODE_PATTERN = "^(api|local_key|hybrid)$"
AUTHORIZATION_MODE_PATTERN = "^(api_token|device_key|hybrid)$"
VALIDATION_RESULT_PATTERN = "^(pending|passed|failed)$"
MODEL_TYPE_PATTERN = "^(router|expert)$"


class ReleaseRequest(BaseModel):
    model_id: str
    target_devices: list[str] = Field(default_factory=list)
    target_buyers: list[str] = Field(default_factory=list)
    delivery_mode: str = Field(default="local_key", pattern=DELIVERY_MODE_PATTERN)
    authorization_mode: str = Field(default="device_key", pattern=AUTHORIZATION_MODE_PATTERN)
    runtime_encryption: bool = True
    api_access_key_label: str | None = None
    local_key_label: str | None = None


class ApproveRequest(BaseModel):
    model_id: str
    validation_asset_ids: list[str] = Field(default_factory=list)
    validation_result: str = Field(default="passed", pattern=VALIDATION_RESULT_PATTERN)
    validation_summary: str | None = None


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


def _build_platform_meta(model: ModelRecord) -> dict[str, Any]:
    payload = dict(model.manifest or {})
    meta = payload.get("platform_meta")
    return meta if isinstance(meta, dict) else {}


def _source_label(source_type: str | None) -> str:
    mapping = {
        "initial_algorithm": "初始算法",
        "pretrained_seed": "预训练模型",
        "finetuned_candidate": "微调候选",
        "delivery_candidate": "交付候选",
    }
    return mapping.get(str(source_type or ""), "交付候选")


def _submitted_summary(model: ModelRecord) -> str:
    meta = _build_platform_meta(model)
    source_label = _source_label(meta.get("model_source_type"))
    if source_label in {"初始算法", "预训练模型"}:
        return f"供应商已提交{source_label}，等待结合客户数据继续微调或进入验证。"
    return "供应商已提交基于客户数据迭代后的候选模型，等待平台验证。"


def _get_accessible_model_or_404(db: Session, current_user: AuthUser, model_id: str) -> ModelRecord:
    model = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    if is_platform_user(current_user.roles):
        return model

    if is_supplier_user(current_user.roles):
        if model.owner_tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
        return model

    if is_buyer_user(current_user.roles):
        releases = (
            db.query(ModelRelease)
            .filter(ModelRelease.model_id == model.id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
            .order_by(ModelRelease.created_at.desc())
            .all()
        )
        buyer_code = current_user.tenant_code
        for release in releases:
            targets = release.target_buyers or []
            if not targets or (buyer_code and buyer_code in targets):
                return model
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.get("")
def list_models(
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    query = db.query(ModelRecord).order_by(ModelRecord.created_at.desc())
    if is_platform_user(current_user.roles):
        rows = query.all()
    elif is_supplier_user(current_user.roles):
        rows = query.filter(ModelRecord.owner_tenant_id == current_user.tenant_id).all()
    elif is_buyer_user(current_user.roles):
        all_rows = query.all()
        buyer_code = current_user.tenant_code
        rows = []
        for row in all_rows:
            releases = (
                db.query(ModelRelease)
                .filter(ModelRelease.model_id == row.id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
                .order_by(ModelRelease.created_at.desc())
                .all()
            )
            if not releases:
                continue
            allowed = False
            for release in releases:
                targets = release.target_buyers or []
                if not targets or (buyer_code and buyer_code in targets):
                    allowed = True
                    break
            if allowed:
                rows.append(row)
    else:
        rows = []
    return [
        {
            **build_model_registry_payload(row),
            "status": row.status,
            "platform_meta": _build_platform_meta(row),
        }
        for row in rows
    ]


@router.get("/{model_id}/timeline")
def get_model_timeline(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    model = _get_accessible_model_or_404(db, current_user, model_id)
    release_rows = (
        db.query(ModelRelease)
        .filter(ModelRelease.model_id == model.id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .all()
    )

    if is_buyer_user(current_user.roles):
        buyer_code = current_user.tenant_code
        release_rows = [row for row in release_rows if not row.target_buyers or (buyer_code and buyer_code in (row.target_buyers or []))]

    user_ids = {model.created_by, *[row.released_by for row in release_rows]}
    user_map = {
        row.id: row.username
        for row in db.query(User).filter(User.id.in_([value for value in user_ids if value])).all()
    }

    approve_log = (
        db.query(AuditLog)
        .filter(
            AuditLog.resource_type == "model",
            AuditLog.resource_id == model.id,
            AuditLog.action == actions.MODEL_APPROVE,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )

    release_logs = {}
    release_ids = [row.id for row in release_rows]
    if release_ids:
        for log in (
            db.query(AuditLog)
            .filter(
                AuditLog.resource_type == "model_release",
                AuditLog.resource_id.in_(release_ids),
                AuditLog.action == actions.MODEL_RELEASE,
            )
            .order_by(AuditLog.created_at.desc())
            .all()
        ):
            release_logs[log.resource_id] = log

    timeline: list[dict[str, object]] = [
        {
            "stage": "submitted",
            "title": "模型提交入库",
            "status": MODEL_STATUS_SUBMITTED,
            "created_at": model.created_at,
            "actor_username": user_map.get(model.created_by, "unknown"),
            "summary": _submitted_summary(model),
            "meta": {
                "model_code": model.model_code,
                "version": model.version,
                "task_type": model.manifest.get("task_type", ""),
                **_build_platform_meta(model),
            },
        }
    ]

    if approve_log or model.status in {MODEL_STATUS_APPROVED, MODEL_STATUS_RELEASED}:
        timeline.append(
            {
                "stage": "approved",
                "title": "平台审批准入",
                "status": MODEL_STATUS_APPROVED,
                "created_at": approve_log.created_at if approve_log else None,
                "actor_username": approve_log.actor_username if approve_log else "-",
                "summary": "平台已确认模型版本、来源和交付口径。",
                "meta": approve_log.detail if approve_log else {},
            }
        )

    for release in sorted(release_rows, key=lambda row: row.created_at):
        release_log = release_logs.get(release.id)
        timeline.append(
            {
                "stage": "released",
                "title": "签名发布与授权交付",
                "status": MODEL_STATUS_RELEASED,
                "created_at": release.created_at,
                "actor_username": release_log.actor_username if release_log else user_map.get(release.released_by, "unknown"),
                "summary": "平台已把该模型发布到授权设备和买家范围。",
                "meta": {
                    "release_id": release.id,
                    "target_devices": release.target_devices or [],
                    "target_buyers": release.target_buyers or [],
                    "status": release.status,
                    "delivery_mode": (release_log.detail or {}).get("delivery_mode") if release_log else None,
                    "authorization_mode": (release_log.detail or {}).get("authorization_mode") if release_log else None,
                    "runtime_encryption": (release_log.detail or {}).get("runtime_encryption") if release_log else None,
                    "api_access_key_preview": (release_log.detail or {}).get("api_access_key_preview") if release_log else None,
                    "local_key_label": (release_log.detail or {}).get("local_key_label") if release_log else None,
                },
            }
        )

    return {
        "model": {
            **build_model_registry_payload(model),
            "status": model.status,
            "platform_meta": _build_platform_meta(model),
        },
        "timeline": timeline,
        "releases": [
            {
                "release_id": row.id,
                "status": row.status,
                "created_at": row.created_at,
                "released_by": user_map.get(row.released_by, "unknown"),
                "target_devices": row.target_devices or [],
                "target_buyers": row.target_buyers or [],
                "signature_status": "SIGNED",
                "delivery_mode": (release_logs.get(row.id).detail or {}).get("delivery_mode") if release_logs.get(row.id) else None,
                "authorization_mode": (release_logs.get(row.id).detail or {}).get("authorization_mode") if release_logs.get(row.id) else None,
                "runtime_encryption": (release_logs.get(row.id).detail or {}).get("runtime_encryption") if release_logs.get(row.id) else None,
                "api_access_key_preview": (release_logs.get(row.id).detail or {}).get("api_access_key_preview") if release_logs.get(row.id) else None,
                "local_key_label": (release_logs.get(row.id).detail or {}).get("local_key_label") if release_logs.get(row.id) else None,
            }
            for row in release_rows
        ],
    }


@router.post("/register")
def register_model_package(
    request: Request,
    package: UploadFile = File(...),
    model_source_type: str = Form(default="delivery_candidate"),
    base_model_ref: str = Form(default=""),
    training_round: str = Form(default=""),
    dataset_label: str = Form(default=""),
    training_summary: str = Form(default=""),
    model_type: str = Form(default=MODEL_TYPE_EXPERT),
    runtime: str = Form(default="python"),
    plugin_name: str = Form(default=""),
    inputs_json: str = Form(default=""),
    outputs_json: str = Form(default=""),
    gpu_mem_mb: str = Form(default=""),
    latency_ms: str = Form(default=""),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_SUBMIT_ROLES)),
):
    if not package.filename.endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .zip model package is allowed")
    if model_source_type not in {"initial_algorithm", "pretrained_seed", "finetuned_candidate", "delivery_candidate"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid model_source_type")
    if model_type not in {MODEL_TYPE_ROUTER, MODEL_TYPE_EXPERT}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid model_type")

    package_bytes = package.file.read()
    settings = get_settings()

    try:
        parsed = parse_and_validate_model_package(package_bytes, settings.model_signing_public_key)
    except ModelPackageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    existing = (
        db.query(ModelRecord)
        .filter(
            ModelRecord.model_code == parsed.manifest["model_id"],
            ModelRecord.version == parsed.manifest["version"],
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Model code+version already exists")

    model_id = str(uuid.uuid4())
    os.makedirs(settings.model_repo_path, exist_ok=True)
    uris = persist_model_package(settings.model_repo_path, model_id, parsed)

    is_supplier_submit = ROLE_SUPPLIER_ENGINEER in expand_roles(current_user.roles)
    model_status = MODEL_STATUS_SUBMITTED if is_supplier_submit else MODEL_STATUS_APPROVED
    audit_action = actions.MODEL_SUBMIT if is_supplier_submit else actions.MODEL_REGISTER

    model = ModelRecord(
        id=model_id,
        model_code=parsed.manifest["model_id"],
        version=parsed.manifest["version"],
        model_hash=parsed.model_hash,
        model_type=model_type,
        runtime=_clean_optional(runtime) or parsed.manifest.get("runtime") or parsed.manifest.get("model_format") or "python",
        inputs=normalize_model_inputs(_parse_json_or_none(inputs_json) or parsed.manifest.get("inputs") or parsed.manifest.get("input_schema")),
        outputs=normalize_model_outputs(model_type, _parse_json_or_none(outputs_json) or parsed.manifest.get("outputs") or parsed.manifest.get("output_schema")),
        plugin_name=_clean_optional(plugin_name) or parsed.manifest.get("plugin_name") or parsed.manifest.get("task_type") or parsed.manifest["model_id"],
        gpu_mem_mb=int(gpu_mem_mb) if str(gpu_mem_mb).strip() else None,
        latency_ms=int(latency_ms) if str(latency_ms).strip() else None,
        encrypted_uri=uris["encrypted_uri"],
        signature_uri=uris["signature_uri"],
        manifest_uri=uris["manifest_uri"],
        manifest=parsed.manifest,
        status=model_status,
        created_by=current_user.id,
        owner_tenant_id=current_user.tenant_id,
    )
    db.add(model)
    db.commit()

    platform_meta = {
        "model_source_type": model_source_type,
        "base_model_ref": _clean_optional(base_model_ref),
        "training_round": _clean_optional(training_round),
        "dataset_label": _clean_optional(dataset_label),
        "training_summary": _clean_optional(training_summary),
    }
    model.manifest = {
        **model.manifest,
        "model_type": model.model_type,
        "runtime": model.runtime,
        "plugin_name": model.plugin_name,
        "inputs": model.inputs,
        "outputs": model.outputs,
        "platform_meta": {key: value for key, value in platform_meta.items() if value not in (None, "", [], {})},
    }
    db.add(model)
    db.commit()

    record_audit(
        db,
        action=audit_action,
        resource_type="model",
        resource_id=model.id,
        detail={
            "model_code": model.model_code,
            "version": model.version,
            "task_type": model.manifest.get("task_type", ""),
            "model_type": model.model_type,
            "plugin_name": model.plugin_name,
            "platform_meta": _build_platform_meta(model),
        },
        request=request,
        actor=current_user,
    )

    return {
        **build_model_registry_payload(model),
        "status": model.status,
        "platform_meta": _build_platform_meta(model),
    }


@router.post("/approve")
def approve_model(
    payload: ApproveRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_APPROVE_ROLES)),
):
    model = db.query(ModelRecord).filter(ModelRecord.id == payload.model_id).first()
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    if model.status in {MODEL_STATUS_APPROVED, MODEL_STATUS_RELEASED}:
        return {"model_id": model.id, "status": model.status}

    model.status = MODEL_STATUS_APPROVED
    db.add(model)
    db.commit()

    record_audit(
        db,
        action=actions.MODEL_APPROVE,
        resource_type="model",
        resource_id=model.id,
        detail={
            "model_code": model.model_code,
            "version": model.version,
            "validation_asset_ids": payload.validation_asset_ids,
            "validation_result": payload.validation_result,
            "validation_summary": _clean_optional(payload.validation_summary),
        },
        request=request,
        actor=current_user,
    )

    return {
        "model_id": model.id,
        "status": model.status,
        "validation_asset_ids": payload.validation_asset_ids,
        "validation_result": payload.validation_result,
        "validation_summary": _clean_optional(payload.validation_summary),
    }


@router.post("/release")
def release_model(
    payload: ReleaseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_RELEASE_ROLES)),
):
    model = db.query(ModelRecord).filter(ModelRecord.id == payload.model_id).first()
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    if model.status not in {MODEL_STATUS_APPROVED, MODEL_STATUS_RELEASED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Model must be APPROVED before release",
        )
    if payload.delivery_mode == "api" and payload.authorization_mode == "device_key":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API delivery requires api_token or hybrid authorization")
    if payload.delivery_mode == "local_key" and payload.authorization_mode == "api_token":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Local encrypted delivery requires device_key or hybrid authorization")
    if payload.delivery_mode == "hybrid" and payload.authorization_mode != "hybrid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Hybrid delivery requires hybrid authorization_mode")

    api_access_key_preview = None
    if payload.delivery_mode in {"api", "hybrid"}:
        label = _clean_optional(payload.api_access_key_label) or "vh_api"
        api_access_key_preview = f"{label}_{uuid.uuid4().hex[:12]}"

    local_key_label = None
    if payload.delivery_mode in {"local_key", "hybrid"}:
        local_key_label = _clean_optional(payload.local_key_label) or "edge/keys/model_decrypt.key"

    release = ModelRelease(
        id=str(uuid.uuid4()),
        model_id=model.id,
        target_devices=payload.target_devices,
        target_buyers=payload.target_buyers,
        status=MODEL_RELEASE_STATUS_RELEASED,
        released_by=current_user.id,
    )

    model.status = MODEL_STATUS_RELEASED
    db.add(release)
    db.add(model)
    db.commit()

    record_audit(
        db,
        action=actions.MODEL_RELEASE,
        resource_type="model_release",
        resource_id=release.id,
        detail={
            "model_id": model.id,
            "target_devices": payload.target_devices,
            "target_buyers": payload.target_buyers,
            "delivery_mode": payload.delivery_mode,
            "authorization_mode": payload.authorization_mode,
            "runtime_encryption": payload.runtime_encryption,
            "api_access_key_preview": api_access_key_preview,
            "local_key_label": local_key_label,
        },
        request=request,
        actor=current_user,
    )

    return {
        "release_id": release.id,
        "model_id": release.model_id,
        "target_devices": release.target_devices,
        "target_buyers": payload.target_buyers,
        "status": release.status,
        "delivery_mode": payload.delivery_mode,
        "authorization_mode": payload.authorization_mode,
        "runtime_encryption": payload.runtime_encryption,
        "api_access_key_preview": api_access_key_preview,
        "local_key_label": local_key_label,
    }
