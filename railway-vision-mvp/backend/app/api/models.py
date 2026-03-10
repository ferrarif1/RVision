import json
import os
import uuid
from datetime import datetime
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
from app.db.models import AuditLog, DataAsset, Device, InferenceResult, InferenceTask, ModelRecord, ModelRelease, Tenant, User
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
from app.services.model_readiness_service import build_model_release_risk_summary
from app.services.model_readiness_service import build_model_validation_report
from app.services.model_readiness_service import merge_platform_meta
from app.services.model_package_service import (
    ModelPackageError,
    parse_and_validate_model_package,
    persist_model_package,
)
from app.services.model_router_service import task_type_from_model
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
    model_id: str = Field(description="模型ID / Model record ID to release")
    target_devices: list[str] = Field(default_factory=list, description="目标设备列表 / Target edge device codes")
    target_buyers: list[str] = Field(default_factory=list, description="目标买家列表 / Target buyer tenant codes")
    delivery_mode: str = Field(default="local_key", pattern=DELIVERY_MODE_PATTERN, description="交付方式 / Delivery mode: api|local_key|hybrid")
    authorization_mode: str = Field(default="device_key", pattern=AUTHORIZATION_MODE_PATTERN, description="授权方式 / Authorization mode: api_token|device_key|hybrid")
    runtime_encryption: bool = Field(default=True, description="运行时解密要求 / Require runtime decryption on edge")
    api_access_key_label: str | None = Field(default=None, description="API访问键标签 / Optional API key label prefix")
    local_key_label: str | None = Field(default=None, description="本地密钥标签 / Optional local key path label")


class ApproveRequest(BaseModel):
    model_id: str = Field(description="模型ID / Model record ID to approve")
    validation_asset_ids: list[str] = Field(default_factory=list, description="验证资产ID列表 / Validation asset IDs")
    validation_result: str = Field(default="passed", pattern=VALIDATION_RESULT_PATTERN, description="验证结论 / Validation result: pending|passed|failed")
    validation_summary: str | None = Field(default=None, description="验证摘要 / Optional validation summary")


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


def _readiness_summary(meta: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = meta.get(key)
    return value if isinstance(value, dict) else None


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


def _task_type_keywords(task_type: str | None) -> list[str]:
    normalized = str(task_type or "").strip().lower()
    if normalized == "car_number_ocr":
        return ["车号", "车厢号", "车皮号", "编号", "ocr", "number", "railcar", "wagon", "thumb", "car"]
    if normalized == "bolt_missing_detect":
        return ["螺栓", "bolt", "紧固件", "缺失", "fastener"]
    if normalized == "object_detect":
        return ["目标", "检测", "detect", "car", "person", "train", "bus", "vehicle"]
    return [normalized] if normalized else []


def _build_capability_summary(model: ModelRecord) -> dict[str, Any]:
    platform_meta = _build_platform_meta(model)
    task_type = task_type_from_model(model)
    source_type = str(platform_meta.get("model_source_type") or "").strip() or "delivery_candidate"
    keywords = _task_type_keywords(task_type)
    task_label = {
        "car_number_ocr": "车号文本识别",
        "object_detect": "目标检测",
        "bolt_missing_detect": "螺栓缺失检测",
    }.get(task_type or "", task_type or "通用模型")
    summary_parts = [
        f"当前模型定位为{task_label}",
        f"来源类型：{_source_label(source_type)}",
    ]
    if platform_meta.get("training_summary"):
        summary_parts.append(f"训练摘要：{platform_meta.get('training_summary')}")
    elif platform_meta.get("dataset_label"):
        summary_parts.append(f"数据标签：{platform_meta.get('dataset_label')}")
    return {
        "task_type": task_type,
        "task_label": task_label,
        "source_type": source_type,
        "source_label": _source_label(source_type),
        "plugin_name": model.plugin_name,
        "dataset_label": platform_meta.get("dataset_label"),
        "training_summary": platform_meta.get("training_summary"),
        "keywords": keywords,
        "summary": "；".join(summary_parts),
    }


def _asset_suggestion_rows(
    db: Session,
    *,
    current_user: AuthUser,
    model: ModelRecord,
    validation_asset_ids: list[str],
) -> list[dict[str, Any]]:
    capability = _build_capability_summary(model)
    task_type = capability.get("task_type")
    keywords = [str(item).strip().lower() for item in capability.get("keywords") or [] if str(item).strip()]
    query = db.query(DataAsset).order_by(DataAsset.created_at.desc())
    if is_buyer_user(current_user.roles):
        query = query.filter(DataAsset.buyer_tenant_id == current_user.tenant_id)
    rows = query.limit(240).all()
    suggestions: list[dict[str, Any]] = []
    for asset in rows:
        if asset.asset_type == "archive":
            continue
        meta = asset.meta if isinstance(asset.meta, dict) else {}
        haystacks = [
            str(asset.file_name or "").lower(),
            str(meta.get("dataset_label") or "").lower(),
            str(meta.get("use_case") or "").lower(),
            str(meta.get("intended_model_code") or "").lower(),
            str(meta.get("archive_kind") or "").lower(),
        ]
        score = 0
        reason_tags: list[str] = []
        if asset.id in validation_asset_ids:
            score += 120
            reason_tags.append("历史验证资产")
        intended_model_code = str(meta.get("intended_model_code") or "").strip().lower()
        if intended_model_code and intended_model_code == str(model.model_code or "").strip().lower():
            score += 45
            reason_tags.append("用途指向当前模型")
        asset_purpose = str(meta.get("asset_purpose") or "").strip().lower()
        if asset_purpose == "validation":
            score += 22
            reason_tags.append("验证用途")
        elif asset_purpose == "inference":
            score += 14
            reason_tags.append("推理用途")
        elif asset_purpose == "training":
            score += 8
        matched_keywords = [keyword for keyword in keywords if keyword and any(keyword in item for item in haystacks)]
        if matched_keywords:
            score += 12 + (len(matched_keywords) * 8)
            reason_tags.append(f"命中能力关键词 {', '.join(dict.fromkeys(matched_keywords[:3]))}")
        if task_type == "car_number_ocr" and asset.asset_type == "image":
            score += 10
        if task_type == "bolt_missing_detect" and asset.asset_type == "image":
            score += 6
        if score <= 0:
            continue
        suggestions.append(
            {
                "id": asset.id,
                "file_name": asset.file_name,
                "asset_type": asset.asset_type,
                "created_at": asset.created_at,
                "meta": {
                    "asset_purpose": meta.get("asset_purpose"),
                    "dataset_label": meta.get("dataset_label"),
                    "use_case": meta.get("use_case"),
                    "intended_model_code": meta.get("intended_model_code"),
                },
                "score": score,
                "reason_tags": reason_tags,
            }
        )
    suggestions.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("created_at") or "")), reverse=False)
    return suggestions[:6]


def _validation_result_summary(result: InferenceResult | None) -> dict[str, Any] | None:
    if not result:
        return None
    result_json = result.result_json if isinstance(result.result_json, dict) else {}
    summary = result_json.get("summary") if isinstance(result_json.get("summary"), dict) else {}
    predictions = result_json.get("predictions") if isinstance(result_json.get("predictions"), list) else []
    first_prediction = predictions[0] if predictions and isinstance(predictions[0], dict) else {}
    recognized_text = (
        str(summary.get("car_number") or "").strip()
        or str(first_prediction.get("text") or first_prediction.get("attributes", {}).get("text") or "").strip()
        or None
    )
    confidence = first_prediction.get("score") or summary.get("confidence")
    return {
        "result_id": result.id,
        "alert_level": result.alert_level,
        "duration_ms": result.duration_ms,
        "recognized_text": recognized_text,
        "prediction_count": len(predictions),
        "confidence": confidence,
        "summary": summary,
        "created_at": result.created_at,
    }


def _recent_validation_tasks(
    db: Session,
    *,
    current_user: AuthUser,
    model: ModelRecord,
) -> dict[str, Any]:
    query = db.query(InferenceTask).filter(InferenceTask.model_id == model.id).order_by(InferenceTask.created_at.desc())
    if is_buyer_user(current_user.roles):
        query = query.filter(InferenceTask.buyer_tenant_id == current_user.tenant_id)
    tasks = query.limit(12).all()
    asset_ids = [row.asset_id for row in tasks if row.asset_id]
    asset_map = {row.id: row for row in db.query(DataAsset).filter(DataAsset.id.in_(asset_ids)).all()} if asset_ids else {}
    task_ids = [row.id for row in tasks]
    result_rows = (
        db.query(InferenceResult)
        .filter(InferenceResult.task_id.in_(task_ids))
        .order_by(InferenceResult.created_at.desc())
        .all()
        if task_ids
        else []
    )
    latest_result_by_task_id: dict[str, InferenceResult] = {}
    for row in result_rows:
        latest_result_by_task_id.setdefault(row.task_id, row)

    payload = []
    success_count = 0
    failed_count = 0
    running_count = 0
    for row in tasks:
        asset = asset_map.get(row.asset_id)
        latest_result = latest_result_by_task_id.get(row.id)
        if row.status == "SUCCEEDED":
            success_count += 1
        elif row.status == "FAILED":
            failed_count += 1
        else:
            running_count += 1
        payload.append(
            {
                "id": row.id,
                "task_type": row.task_type,
                "status": row.status,
                "asset_id": row.asset_id,
                "asset_file_name": asset.file_name if asset else None,
                "device_code": row.device_code,
                "created_at": row.created_at,
                "finished_at": row.finished_at,
                "error_message": row.error_message,
                "result": _validation_result_summary(latest_result),
            }
        )
    return {
        "rows": payload,
        "counts": {
            "total": len(payload),
            "success": success_count,
            "failed": failed_count,
            "running": running_count,
        },
    }


def _release_scope_candidates(db: Session) -> dict[str, list[dict[str, Any]]]:
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
    return {
        "devices": [
            {
                "code": row.code,
                "name": row.name,
                "status": row.status,
                "last_seen_at": row.last_seen_at,
            }
            for row in devices
        ],
        "buyers": [
            {
                "tenant_code": row.tenant_code,
                "name": row.name,
                "status": row.status,
            }
            for row in buyers
        ],
    }


def _latest_release_record(db: Session, model_id: str) -> ModelRelease | None:
    return (
        db.query(ModelRelease)
        .filter(ModelRelease.model_id == model_id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .first()
    )


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
    owner_tenant_ids = [row.owner_tenant_id for row in rows if row.owner_tenant_id]
    owner_tenant_map = {
        row.id: row
        for row in db.query(Tenant).filter(Tenant.id.in_(owner_tenant_ids)).all()
    }
    return [
        {
            **build_model_registry_payload(row),
            "status": row.status,
            "platform_meta": _build_platform_meta(row),
            "validation_report": _readiness_summary(_build_platform_meta(row), "validation_report"),
            "latest_release_risk_summary": _readiness_summary(_build_platform_meta(row), "latest_release_risk_summary"),
            "owner_tenant_code": owner_tenant_map.get(row.owner_tenant_id).tenant_code if owner_tenant_map.get(row.owner_tenant_id) else None,
            "owner_tenant_name": owner_tenant_map.get(row.owner_tenant_id).name if owner_tenant_map.get(row.owner_tenant_id) else None,
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
                "meta": {
                    **(approve_log.detail if approve_log else {}),
                    "validation_report": _readiness_summary(_build_platform_meta(model), "validation_report"),
                },
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
                    "release_risk_summary": (release_log.detail or {}).get("release_risk_summary") if release_log else None,
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


@router.get("/{model_id}/readiness")
def get_model_readiness(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    model = _get_accessible_model_or_404(db, current_user, model_id)
    validation_report = build_model_validation_report(db, model)
    default_release_risk_summary = build_model_release_risk_summary(
        model,
        validation_report,
        target_devices=[],
        target_buyers=[],
        delivery_mode="local_key",
        authorization_mode="device_key",
        runtime_encryption=True,
        api_access_key_label=None,
        local_key_label=None,
    )
    platform_meta = _build_platform_meta(model)
    return {
        "model": {
            **build_model_registry_payload(model),
            "status": model.status,
            "platform_meta": platform_meta,
        },
        "validation_report": validation_report,
        "default_release_risk_summary": default_release_risk_summary,
        "stored_validation_report": _readiness_summary(platform_meta, "validation_report"),
        "stored_release_risk_summary": _readiness_summary(platform_meta, "latest_release_risk_summary"),
    }


@router.get("/{model_id}/approval-workbench")
def get_model_approval_workbench(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    model = _get_accessible_model_or_404(db, current_user, model_id)
    validation_report = build_model_validation_report(db, model)
    default_release_risk_summary = build_model_release_risk_summary(
        model,
        validation_report,
        target_devices=[],
        target_buyers=[],
        delivery_mode="local_key",
        authorization_mode="device_key",
        runtime_encryption=True,
        api_access_key_label=None,
        local_key_label=None,
    )
    capability = _build_capability_summary(model)
    suggested_assets = _asset_suggestion_rows(
        db,
        current_user=current_user,
        model=model,
        validation_asset_ids=validation_report.get("validation_asset_ids") or [],
    )
    recent_tasks = _recent_validation_tasks(db, current_user=current_user, model=model)
    platform_meta = _build_platform_meta(model)
    return {
        "model": {
            **build_model_registry_payload(model),
            "status": model.status,
            "platform_meta": platform_meta,
        },
        "capability": capability,
        "recommended_task_type": capability.get("task_type"),
        "recommended_device_code": "edge-01",
        "readiness": {
            "validation_report": validation_report,
            "default_release_risk_summary": default_release_risk_summary,
            "stored_validation_report": _readiness_summary(platform_meta, "validation_report"),
            "stored_release_risk_summary": _readiness_summary(platform_meta, "latest_release_risk_summary"),
        },
        "suggested_assets": suggested_assets,
        "recent_validation_tasks": recent_tasks["rows"],
        "recent_validation_counts": recent_tasks["counts"],
    }


@router.get("/{model_id}/release-workbench")
def get_model_release_workbench(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_RELEASE_ROLES)),
):
    model = _get_accessible_model_or_404(db, current_user, model_id)
    validation_report = build_model_validation_report(db, model)
    latest_release = _latest_release_record(db, model.id)
    scope_candidates = _release_scope_candidates(db)
    platform_meta = _build_platform_meta(model)
    capability = _build_capability_summary(model)
    recommended_target_devices = list(latest_release.target_devices or []) if latest_release else []
    recommended_target_buyers = list(latest_release.target_buyers or []) if latest_release else []
    if not recommended_target_devices and scope_candidates["devices"]:
        recommended_target_devices = [scope_candidates["devices"][0]["code"]]
    if not recommended_target_buyers and scope_candidates["buyers"]:
        recommended_target_buyers = [scope_candidates["buyers"][0]["tenant_code"]]
    recommended_config = {
        "delivery_mode": "local_key",
        "authorization_mode": "device_key",
        "runtime_encryption": True,
        "api_access_key_label": None,
        "local_key_label": "edge/keys/model_decrypt.key",
    }
    release_risk_summary = build_model_release_risk_summary(
        model,
        validation_report,
        target_devices=recommended_target_devices,
        target_buyers=recommended_target_buyers,
        delivery_mode=recommended_config["delivery_mode"],
        authorization_mode=recommended_config["authorization_mode"],
        runtime_encryption=recommended_config["runtime_encryption"],
        api_access_key_label=recommended_config["api_access_key_label"],
        local_key_label=recommended_config["local_key_label"],
    )
    return {
        "model": {
            **build_model_registry_payload(model),
            "status": model.status,
            "platform_meta": platform_meta,
        },
        "capability": capability,
        "readiness": {
            "validation_report": validation_report,
            "release_risk_summary": release_risk_summary,
            "stored_release_risk_summary": _readiness_summary(platform_meta, "latest_release_risk_summary"),
        },
        "scope_candidates": scope_candidates,
        "recommended_release": {
            "target_devices": recommended_target_devices,
            "target_buyers": recommended_target_buyers,
            **recommended_config,
        },
        "latest_release": {
            "id": latest_release.id,
            "target_devices": latest_release.target_devices,
            "target_buyers": latest_release.target_buyers,
            "created_at": latest_release.created_at,
        }
        if latest_release
        else None,
    }


@router.post("/release-readiness")
def get_model_release_readiness(
    payload: ReleaseRequest,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_RELEASE_ROLES)),
):
    model = _get_accessible_model_or_404(db, current_user, payload.model_id)
    validation_report = build_model_validation_report(db, model)
    release_risk_summary = build_model_release_risk_summary(
        model,
        validation_report,
        target_devices=payload.target_devices,
        target_buyers=payload.target_buyers,
        delivery_mode=payload.delivery_mode,
        authorization_mode=payload.authorization_mode,
        runtime_encryption=payload.runtime_encryption,
        api_access_key_label=payload.api_access_key_label,
        local_key_label=payload.local_key_label,
    )
    return {
        "model_id": model.id,
        "status": model.status,
        "validation_report": validation_report,
        "release_risk_summary": release_risk_summary,
    }


@router.post("/register")
def register_model_package(
    request: Request,
    package: UploadFile = File(..., description="模型包ZIP / Model package zip file"),
    model_source_type: str = Form(default="delivery_candidate", description="模型来源类型 / Source type: initial_algorithm|pretrained_seed|finetuned_candidate|delivery_candidate"),
    base_model_ref: str = Form(default="", description="基线模型引用 / Base model reference, e.g. code:version"),
    training_round: str = Form(default="", description="训练轮次 / Training round label"),
    dataset_label: str = Form(default="", description="数据批次标签 / Dataset batch label"),
    training_summary: str = Form(default="", description="训练摘要 / Training summary"),
    model_type: str = Form(default=MODEL_TYPE_EXPERT, description="模型类型 / Model type: router|expert"),
    runtime: str = Form(default="python", description="运行时类型 / Runtime, e.g. python/onnxruntime"),
    plugin_name: str = Form(default="", description="插件名称 / Plugin name used by edge runtime"),
    inputs_json: str = Form(default="", description="输入协议JSON / Input schema JSON object"),
    outputs_json: str = Form(default="", description="输出协议JSON / Output schema JSON object"),
    gpu_mem_mb: str = Form(default="", description="显存需求MB / Optional GPU memory requirement in MB"),
    latency_ms: str = Form(default="", description="时延指标ms / Optional latency metric in milliseconds"),
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

    # 关键流程：供应商提交先进入 SUBMITTED，平台角色录入可直接 APPROVED。
    # Core flow: supplier submit stays SUBMITTED; platform-side register can be pre-approved.
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

    validation_report = build_model_validation_report(db, model, override_validation_asset_ids=payload.validation_asset_ids)
    if not validation_report.get("can_approve"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Model failed validation gate: {validation_report.get('summary')}")

    resolved_validation_asset_ids = payload.validation_asset_ids or validation_report.get("validation_asset_ids") or []
    resolved_validation_summary = _clean_optional(payload.validation_summary) or validation_report.get("summary")
    enriched_validation_report = {
        **validation_report,
        "validation_asset_ids": resolved_validation_asset_ids,
        "approved_by": current_user.username,
        "approved_at": datetime.utcnow().isoformat(),
    }

    if model.status not in {MODEL_STATUS_APPROVED, MODEL_STATUS_RELEASED}:
        model.status = MODEL_STATUS_APPROVED
    merge_platform_meta(
        model,
        {
            "validation_asset_ids": resolved_validation_asset_ids,
            "validation_report": enriched_validation_report,
            "validation_summary": resolved_validation_summary,
        },
    )
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
            "validation_asset_ids": resolved_validation_asset_ids,
            "validation_result": validation_report.get("validation_result") or payload.validation_result,
            "validation_summary": resolved_validation_summary,
            "validation_report": enriched_validation_report,
        },
        request=request,
        actor=current_user,
    )

    return {
        "model_id": model.id,
        "status": model.status,
        "validation_asset_ids": resolved_validation_asset_ids,
        "validation_result": validation_report.get("validation_result") or payload.validation_result,
        "validation_summary": resolved_validation_summary,
        "validation_report": enriched_validation_report,
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
    # 交付模式与授权模式必须匹配，避免“只能API交付却没有API授权”等错误组合。
    # Delivery mode must be compatible with authorization mode.
    if payload.delivery_mode == "api" and payload.authorization_mode == "device_key":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API delivery requires api_token or hybrid authorization")
    if payload.delivery_mode == "local_key" and payload.authorization_mode == "api_token":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Local encrypted delivery requires device_key or hybrid authorization")
    if payload.delivery_mode == "hybrid" and payload.authorization_mode != "hybrid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Hybrid delivery requires hybrid authorization_mode")

    validation_report = build_model_validation_report(db, model)
    release_risk_summary = build_model_release_risk_summary(
        model,
        validation_report,
        target_devices=payload.target_devices,
        target_buyers=payload.target_buyers,
        delivery_mode=payload.delivery_mode,
        authorization_mode=payload.authorization_mode,
        runtime_encryption=payload.runtime_encryption,
        api_access_key_label=payload.api_access_key_label,
        local_key_label=payload.local_key_label,
    )
    if not release_risk_summary.get("can_release"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Release blocked: {release_risk_summary.get('summary')}")

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
    merge_platform_meta(
        model,
        {
            "latest_release_risk_summary": {
                **release_risk_summary,
                "released_by": current_user.username,
            }
        },
    )
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
            "release_risk_summary": release_risk_summary,
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
        "release_risk_summary": release_risk_summary,
    }
