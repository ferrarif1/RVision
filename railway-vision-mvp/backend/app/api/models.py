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
from app.core.constants import MODEL_STATUS_REJECTED
from app.core.constants import MODEL_STATUS_RELEASED
from app.core.constants import MODEL_STATUS_SUBMITTED
from app.core.config import get_settings
from app.core.ui_errors import raise_ui_error
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


class RejectRequest(BaseModel):
    model_id: str = Field(description="模型ID / Model record ID to reject")
    rejection_reason: str = Field(description="驳回原因 / Rejection reason")
    corrective_action: str | None = Field(default=None, description="修正建议 / Optional corrective action")


class RequestEvidenceRequest(BaseModel):
    model_id: str = Field(description="模型ID / Model record ID to request more evidence for")
    requested_items: list[str] = Field(default_factory=list, description="要求补充的材料项 / Requested evidence items")
    request_summary: str | None = Field(default=None, description="补材料说明 / Optional request summary")


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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "model_metadata_json_invalid",
            "填写的 JSON 元信息格式不正确。",
            next_step="请检查 JSON 语法，例如逗号、引号和大括号是否完整。",
            raw_detail=str(exc),
        )
    if not isinstance(parsed, dict):
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "model_metadata_json_object_required",
            "JSON 元信息必须是对象格式。",
            next_step="请使用 {\"key\": \"value\"} 这样的对象格式填写。",
        )
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
    if normalized == "inspection_mark_ocr":
        return ["定检标记", "检修标记", "检修记录", "inspection mark", "maintenance mark", "日期", "车型代码"]
    if normalized == "performance_mark_ocr":
        return ["性能标记", "性能文字", "performance mark", "性能代码"]
    if normalized == "door_lock_state_detect":
        return ["门锁", "锁闭", "敞开", "door lock", "lock state", "door state"]
    if normalized == "connector_defect_detect":
        return ["连接件", "连接件缺陷", "松动", "变形", "缺失", "connector defect", "connector"]
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
        "inspection_mark_ocr": "定检标记识别",
        "performance_mark_ocr": "性能标记识别",
        "door_lock_state_detect": "门锁状态识别",
        "connector_defect_detect": "连接件缺陷识别",
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
        if task_type in {"car_number_ocr", "inspection_mark_ocr", "performance_mark_ocr"} and asset.asset_type == "image":
            score += 10
        if task_type in {"bolt_missing_detect", "door_lock_state_detect", "connector_defect_detect"} and asset.asset_type == "image":
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


def _latest_model_audit_log(db: Session, model_id: str, action: str) -> AuditLog | None:
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.resource_type == "model",
            AuditLog.resource_id == model_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )


def _governance_summary(db: Session, model: ModelRecord) -> dict[str, Any]:
    approve_log = _latest_model_audit_log(db, model.id, actions.MODEL_APPROVE)
    reject_log = _latest_model_audit_log(db, model.id, actions.MODEL_REJECT)
    request_log = _latest_model_audit_log(db, model.id, actions.MODEL_REQUEST_EVIDENCE)
    logs = [row for row in (approve_log, reject_log, request_log) if row]
    latest_log = max(logs, key=lambda row: row.created_at) if logs else None

    if latest_log and latest_log.action == actions.MODEL_REJECT:
        state = "rejected"
        label = "已驳回"
        summary = (latest_log.detail or {}).get("rejection_reason") or "平台已驳回这版模型，等待修正后重新提交。"
    elif latest_log and latest_log.action == actions.MODEL_REQUEST_EVIDENCE:
        state = "needs_evidence"
        label = "待补材料"
        requested_items = (latest_log.detail or {}).get("requested_items") or []
        summary = (latest_log.detail or {}).get("request_summary") or (
            f"平台要求补充 {len(requested_items)} 项材料后再继续审批。" if requested_items else "平台要求补充材料后再继续审批。"
        )
    elif model.status in {MODEL_STATUS_APPROVED, MODEL_STATUS_RELEASED} or (latest_log and latest_log.action == actions.MODEL_APPROVE):
        state = "approved"
        label = "已审批"
        summary = (approve_log.detail or {}).get("validation_summary") if approve_log else "平台已完成审批，可以进入发布。"
    else:
        state = "submitted"
        label = "待审批"
        summary = "当前模型仍处于待审批状态，建议先完成验证样本运行和证据补齐。"

    return {
        "state": state,
        "label": label,
        "summary": summary,
        "latest_action_at": latest_log.created_at if latest_log else None,
        "latest_action_by": latest_log.actor_username if latest_log else None,
        "approve": {
            "created_at": approve_log.created_at,
            "actor_username": approve_log.actor_username,
            "detail": approve_log.detail or {},
        }
        if approve_log
        else None,
        "reject": {
            "created_at": reject_log.created_at,
            "actor_username": reject_log.actor_username,
            "detail": reject_log.detail or {},
        }
        if reject_log
        else None,
        "request_evidence": {
            "created_at": request_log.created_at,
            "actor_username": request_log.actor_username,
            "detail": request_log.detail or {},
        }
        if request_log
        else None,
    }


def _get_accessible_model_or_404(db: Session, current_user: AuthUser, model_id: str) -> ModelRecord:
    model = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not model:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "model_not_found",
            "模型不存在，或当前账号看不到这版模型。",
            next_step="请回到模型中心刷新列表后，重新选择模型。",
        )

    if is_platform_user(current_user.roles):
        return model

    if is_supplier_user(current_user.roles):
        if model.owner_tenant_id != current_user.tenant_id:
            raise_ui_error(
                status.HTTP_404_NOT_FOUND,
                "model_not_found",
                "模型不存在，或当前账号看不到这版模型。",
                next_step="请确认你正在查看当前供应商租户下的模型。",
            )
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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "model_not_found",
            "模型不存在，或当前账号看不到这版模型。",
            next_step="请确认模型已发布到当前买方范围，或改选一版已发布模型。",
        )

    raise_ui_error(
        status.HTTP_403_FORBIDDEN,
        "model_access_forbidden",
        "当前账号没有权限访问这版模型。",
        next_step="请切换到具备模型权限的账号，或回到当前角色默认工作区。",
    )


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

    approve_log = _latest_model_audit_log(db, model.id, actions.MODEL_APPROVE)
    reject_log = _latest_model_audit_log(db, model.id, actions.MODEL_REJECT)
    request_evidence_log = _latest_model_audit_log(db, model.id, actions.MODEL_REQUEST_EVIDENCE)

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

    if request_evidence_log:
        timeline.append(
            {
                "stage": "request_evidence",
                "title": "平台要求补充材料",
                "status": MODEL_STATUS_SUBMITTED,
                "created_at": request_evidence_log.created_at,
                "actor_username": request_evidence_log.actor_username,
                "summary": (request_evidence_log.detail or {}).get("request_summary") or "平台要求补充运行验证、说明材料或证据包后再继续审批。",
                "meta": request_evidence_log.detail or {},
            }
        )

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

    if reject_log or model.status == MODEL_STATUS_REJECTED:
        timeline.append(
            {
                "stage": "rejected",
                "title": "平台驳回当前模型",
                "status": MODEL_STATUS_REJECTED,
                "created_at": reject_log.created_at if reject_log else None,
                "actor_username": reject_log.actor_username if reject_log else "-",
                "summary": (reject_log.detail or {}).get("rejection_reason") if reject_log else "平台已驳回当前模型版本。",
                "meta": reject_log.detail if reject_log else {},
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
    governance = _governance_summary(db, model)
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
        "governance": governance,
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
    governance = _governance_summary(db, model)
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
        "governance": governance,
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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "model_package_zip_required",
            "这里只接受 ZIP 模型包。",
            next_step="请重新打包成 .zip 后再上传。",
        )
    if model_source_type not in {"initial_algorithm", "pretrained_seed", "finetuned_candidate", "delivery_candidate"}:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "model_source_type_invalid",
            "模型来源填写无效。",
            next_step="请重新选择初始算法、预训练模型、微调候选或交付候选。",
        )
    if model_type not in {MODEL_TYPE_ROUTER, MODEL_TYPE_EXPERT}:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "model_type_invalid",
            "模型类型填写无效。",
            next_step="请重新选择路由模型或专家模型。",
        )

    package_bytes = package.file.read()
    settings = get_settings()

    try:
        parsed = parse_and_validate_model_package(package_bytes, settings.model_signing_public_key)
    except ModelPackageError as exc:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "model_package_invalid",
            "模型包校验失败，当前包不能继续注册。",
            next_step="请确认模型包签名、加密和 manifest 都正确后重新上传。",
            raw_detail=str(exc),
        )

    existing = (
        db.query(ModelRecord)
        .filter(
            ModelRecord.model_code == parsed.manifest["model_id"],
            ModelRecord.version == parsed.manifest["version"],
        )
        .first()
    )
    if existing:
        raise_ui_error(
            status.HTTP_409_CONFLICT,
            "model_version_conflict",
            "同一模型编码和版本已经存在。",
            next_step="请更换一个新的模型版本号后再提交。",
        )

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


@router.post("/request-evidence")
def request_model_evidence(
    payload: RequestEvidenceRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_APPROVE_ROLES)),
):
    model = db.query(ModelRecord).filter(ModelRecord.id == payload.model_id).first()
    if not model:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "model_not_found",
            "模型不存在，或当前账号看不到这版模型。",
            next_step="请回到模型中心刷新列表，再重新选择一版模型。",
        )
    if model.status == MODEL_STATUS_RELEASED:
        raise_ui_error(
            status.HTTP_409_CONFLICT,
            "released_model_evidence_request_blocked",
            "已发布模型不能再发起补材料要求。",
            next_step="如需变更，请先登记新模型版本，再重新走审批。",
        )

    requested_items = [str(item).strip() for item in payload.requested_items if str(item).strip()]
    request_summary = _clean_optional(payload.request_summary) or (
        f"请补充 {len(requested_items)} 项审批材料后再继续验证。" if requested_items else "请补充审批材料后再继续验证。"
    )
    merge_platform_meta(
        model,
        {
            "approval_request_evidence": {
                "requested_items": requested_items,
                "request_summary": request_summary,
                "requested_by": current_user.username,
                "requested_at": datetime.utcnow().isoformat(),
            }
        },
    )
    if model.status == MODEL_STATUS_REJECTED:
        model.status = MODEL_STATUS_SUBMITTED
    db.add(model)
    db.commit()

    detail = {
        "model_code": model.model_code,
        "version": model.version,
        "requested_items": requested_items,
        "request_summary": request_summary,
    }
    record_audit(
        db,
        action=actions.MODEL_REQUEST_EVIDENCE,
        resource_type="model",
        resource_id=model.id,
        detail=detail,
        request=request,
        actor=current_user,
    )
    return {
        "model_id": model.id,
        "status": model.status,
        "request_summary": request_summary,
        "requested_items": requested_items,
    }


@router.post("/reject")
def reject_model(
    payload: RejectRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_APPROVE_ROLES)),
):
    model = db.query(ModelRecord).filter(ModelRecord.id == payload.model_id).first()
    if not model:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "model_not_found",
            "模型不存在，或当前账号看不到这版模型。",
            next_step="请回到模型中心刷新列表，再重新选择一版模型。",
        )
    if model.status == MODEL_STATUS_RELEASED:
        raise_ui_error(
            status.HTTP_409_CONFLICT,
            "released_model_reject_blocked",
            "已发布模型不能直接驳回。",
            next_step="如需变更，请登记一版新模型重新走审批；已发布版本请通过发布策略控制使用范围。",
        )

    rejection_reason = _clean_optional(payload.rejection_reason)
    if not rejection_reason:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "model_rejection_reason_required",
            "驳回时必须填写原因。",
            next_step="请补充具体的驳回原因，再重新提交。",
        )
    corrective_action = _clean_optional(payload.corrective_action)
    model.status = MODEL_STATUS_REJECTED
    merge_platform_meta(
        model,
        {
            "rejection_summary": {
                "rejection_reason": rejection_reason,
                "corrective_action": corrective_action,
                "rejected_by": current_user.username,
                "rejected_at": datetime.utcnow().isoformat(),
            }
        },
    )
    db.add(model)
    db.commit()

    detail = {
        "model_code": model.model_code,
        "version": model.version,
        "rejection_reason": rejection_reason,
        "corrective_action": corrective_action,
    }
    record_audit(
        db,
        action=actions.MODEL_REJECT,
        resource_type="model",
        resource_id=model.id,
        detail=detail,
        request=request,
        actor=current_user,
    )
    return {
        "model_id": model.id,
        "status": model.status,
        "rejection_reason": rejection_reason,
        "corrective_action": corrective_action,
    }


@router.get("/{model_id}/evidence-pack")
def export_model_evidence_pack(
    model_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_APPROVE_ROLES)),
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
    governance = _governance_summary(db, model)
    timeline_payload = get_model_timeline(model_id=model_id, db=db, current_user=current_user)
    latest_release = _latest_release_record(db, model.id)
    payload = {
        "exported_at": datetime.utcnow().isoformat(),
        "exported_by": current_user.username,
        "model": {
            **build_model_registry_payload(model),
            "status": model.status,
            "platform_meta": _build_platform_meta(model),
        },
        "capability": capability,
        "governance": governance,
        "readiness": {
            "validation_report": validation_report,
            "default_release_risk_summary": default_release_risk_summary,
        },
        "suggested_assets": suggested_assets,
        "recent_validation_tasks": recent_tasks["rows"],
        "recent_validation_counts": recent_tasks["counts"],
        "timeline": timeline_payload.get("timeline") or [],
        "releases": timeline_payload.get("releases") or [],
        "latest_release": {
            "id": latest_release.id,
            "created_at": latest_release.created_at,
            "target_devices": latest_release.target_devices or [],
            "target_buyers": latest_release.target_buyers or [],
        }
        if latest_release
        else None,
    }
    record_audit(
        db,
        action=actions.MODEL_EVIDENCE_EXPORT,
        resource_type="model",
        resource_id=model.id,
        detail={"model_code": model.model_code, "version": model.version},
        request=request,
        actor=current_user,
    )
    return payload


@router.post("/approve")
def approve_model(
    payload: ApproveRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_APPROVE_ROLES)),
):
    model = db.query(ModelRecord).filter(ModelRecord.id == payload.model_id).first()
    if not model:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "model_not_found",
            "模型不存在，或当前账号看不到这版模型。",
            next_step="请回到模型中心刷新列表，再重新选择一版模型。",
        )

    validation_report = build_model_validation_report(db, model, override_validation_asset_ids=payload.validation_asset_ids)
    if not validation_report.get("can_approve"):
        raise_ui_error(
            status.HTTP_409_CONFLICT,
            "model_validation_gate_failed",
            "当前模型还没有通过验证门禁，暂时不能审批通过。",
            next_step="请先补充建议验证样本，修复阻断项后再重新审批。",
            raw_detail={"summary": validation_report.get("summary")},
        )

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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "model_not_found",
            "模型不存在，或当前账号看不到这版模型。",
            next_step="请回到模型中心刷新列表，再重新选择一版模型。",
        )
    if model.status not in {MODEL_STATUS_APPROVED, MODEL_STATUS_RELEASED}:
        raise_ui_error(
            status.HTTP_409_CONFLICT,
            "model_not_approved_for_release",
            "模型还没有审批通过，暂时不能发布。",
            next_step="请先到审批工作台完成验证和审批，再继续发布。",
        )
    # 交付模式与授权模式必须匹配，避免“只能API交付却没有API授权”等错误组合。
    # Delivery mode must be compatible with authorization mode.
    if payload.delivery_mode == "api" and payload.authorization_mode == "device_key":
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "release_delivery_authorization_mismatch",
            "当前交付方式和授权方式不匹配。",
            next_step="API 交付请改用 api_token 或 hybrid 授权。",
        )
    if payload.delivery_mode == "local_key" and payload.authorization_mode == "api_token":
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "release_delivery_authorization_mismatch",
            "当前交付方式和授权方式不匹配。",
            next_step="本地加密交付请改用 device_key 或 hybrid 授权。",
        )
    if payload.delivery_mode == "hybrid" and payload.authorization_mode != "hybrid":
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "release_delivery_authorization_mismatch",
            "混合交付必须搭配混合授权方式。",
            next_step="请把 authorization_mode 调整为 hybrid 后再发布。",
        )

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
        raise_ui_error(
            status.HTTP_409_CONFLICT,
            "release_risk_gate_failed",
            "当前模型还没有满足发布前风险门禁，暂时不能发布。",
            next_step="请先处理工作台里的阻断项，再重新执行发布前评估。",
            raw_detail={"summary": release_risk_summary.get("summary")},
        )

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
