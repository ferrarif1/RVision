import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import TASK_STATUS_PENDING
from app.db.database import get_db
from app.db.models import DataAsset, InferenceResult, InferenceRun, InferenceTask, ModelRecord, ModelRelease, ReviewQueue
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import TASK_CREATE_ROLES, TASK_READ_ROLES, is_buyer_user
from app.services.audit_service import record_audit
from app.services.model_router_service import recommend_small_models, task_type_from_model
from app.services.pipeline_service import get_accessible_pipeline_or_404
from app.services.pipeline_service import get_pipeline_catalog
from app.services.pipeline_service import serialize_pipeline

router = APIRouter(prefix="/tasks", tags=["tasks"])
DEFAULT_TASK_POLICY = {
    "upload_raw_video": False,
    "upload_frames": True,
    "desensitize_frames": False,
    "retention_days": 30,
}


class TaskModelRecommendRequest(BaseModel):
    asset_id: str = Field(description="资产ID / Asset ID used for model recommendation")
    task_type: str | None = Field(default=None, description="期望任务类型 / Requested task type")
    device_code: str | None = Field(default=None, description="设备编码 / Edge device code for release-scope filtering")
    intent_text: str | None = Field(default=None, description="业务意图文本 / Natural-language intent for scheduler hints")
    limit: int = Field(default=3, ge=1, le=5, description="返回候选数量 / Number of recommended models")


class TaskCreateRequest(BaseModel):
    pipeline_id: str | None = Field(default=None, description="流水线ID / Pipeline ID (preferred execution entry)")
    model_id: str | None = Field(default=None, description="模型ID / Direct model ID when not using pipeline")
    asset_id: str = Field(description="资产ID / Asset ID to be processed")
    task_type: str | None = Field(default=None, description="任务类型 / Task type such as ocr or defect_detect")
    device_code: str | None = Field(default=None, description="目标设备编码 / Target edge device code")
    policy: dict[str, Any] = Field(default_factory=dict, description="执行策略 / Execution policy overrides")
    use_master_scheduler: bool = Field(default=False, description="是否启用主调度器 / Enable master scheduler when model is not fixed")
    intent_text: str | None = Field(default=None, description="业务意图文本 / Free text intent for scheduler")
    context: dict[str, Any] = Field(default_factory=dict, description="上下文参数 / Runtime context, e.g. camera_id/scene_hint")
    options: dict[str, Any] = Field(default_factory=dict, description="运行选项 / Runtime options for pipeline/plugins")


def _is_model_released_to_buyer(
    db: Session,
    model_id: str,
    buyer_code: str | None,
    device_code: str | None,
) -> bool:
    releases = (
        db.query(ModelRelease)
        .filter(ModelRelease.model_id == model_id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .all()
    )
    for release in releases:
        targets = release.target_buyers or []
        devices = release.target_devices or []
        buyer_ok = not targets or (buyer_code and buyer_code in targets)
        device_ok = not device_code or not devices or device_code in devices
        if buyer_ok and device_ok:
            return True
    return False


def _get_asset_in_scope(db: Session, asset_id: str, current_user: AuthUser) -> DataAsset:
    asset = db.query(DataAsset).filter(DataAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if is_buyer_user(current_user.roles):
        if not current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Buyer tenant missing")
        if asset.buyer_tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Asset not in your tenant scope")
    return asset


def _build_scheduler_detail(decision: dict[str, Any], intent_text: str | None) -> dict[str, Any]:
    return {
        "enabled": True,
        "engine": decision.get("engine"),
        "requested_task_type": decision.get("requested_task_type"),
        "inferred_task_type": decision.get("inferred_task_type"),
        "confidence": decision.get("confidence"),
        "summary": decision.get("summary"),
        "signals": decision.get("signals") or [],
        "selected_model": decision.get("selected_model"),
        "alternatives": decision.get("alternatives") or [],
        "intent_text": intent_text,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    return value


def _build_orchestrator_policy(
    *,
    pipeline_payload: dict[str, Any],
    context: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    return {
        "enabled": True,
        "pipeline": _json_ready(pipeline_payload),
        "context": _json_ready(context),
        "options": _json_ready(options),
    }


@router.post("/recommend-model")
def recommend_task_model(
    payload: TaskModelRecommendRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TASK_CREATE_ROLES)),
):
    asset = _get_asset_in_scope(db, payload.asset_id, current_user)
    decision = recommend_small_models(
        db,
        current_user,
        asset=asset,
        device_code=payload.device_code,
        requested_task_type=payload.task_type,
        intent_text=payload.intent_text,
        limit=payload.limit,
    ).to_dict()

    record_audit(
        db,
        action=actions.MODEL_RECOMMEND,
        resource_type="asset",
        resource_id=asset.id,
        detail={
            "asset_id": asset.id,
            "requested_task_type": payload.task_type,
            "device_code": payload.device_code,
            "intent_text": payload.intent_text,
            "recommendation": decision,
        },
        request=request,
        actor=current_user,
    )
    return decision


@router.post("/create")
def create_task(
    payload: TaskCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TASK_CREATE_ROLES)),
):
    asset = _get_asset_in_scope(db, payload.asset_id, current_user)
    # 优先走 pipeline-first；未提供 pipeline 时再按调度器或显式模型执行。
    # Pipeline-first path has highest priority, then scheduler/direct-model fallback.
    scheduler_enabled = payload.use_master_scheduler or not payload.model_id
    scheduler_detail: dict[str, Any] | None = None
    model: ModelRecord | None = None
    resolved_task_type = payload.task_type
    pipeline_payload: dict[str, Any] | None = None
    pipeline_id: str | None = None

    if payload.pipeline_id:
        pipeline = get_accessible_pipeline_or_404(db, current_user, payload.pipeline_id, device_code=payload.device_code)
        catalog = get_pipeline_catalog(db, pipeline)
        pipeline_payload = serialize_pipeline(pipeline, catalog.router, catalog.models)
        pipeline_id = pipeline.id
        model = catalog.router or next(iter(catalog.models.values()), None)
        resolved_task_type = payload.task_type or "pipeline_orchestrated"
        scheduler_enabled = False

    if not payload.pipeline_id and scheduler_enabled:
        decision = recommend_small_models(
            db,
            current_user,
            asset=asset,
            device_code=payload.device_code,
            requested_task_type=payload.task_type,
            intent_text=payload.intent_text,
            limit=3,
        ).to_dict()
        selected_model = decision.get("selected_model")
        if not selected_model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No schedulable model found")
        model = db.query(ModelRecord).filter(ModelRecord.id == selected_model["model_id"]).first()
        if not model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled model not found")
        resolved_task_type = decision.get("inferred_task_type") or selected_model.get("task_type")
        scheduler_detail = _build_scheduler_detail(decision, payload.intent_text)
    elif not payload.pipeline_id:
        model = db.query(ModelRecord).filter(ModelRecord.id == payload.model_id).first()
        if not model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

        if is_buyer_user(current_user.roles):
            if not _is_model_released_to_buyer(db, model.id, current_user.tenant_code, payload.device_code):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Model not released to your tenant or device")

        manifest_task_type = task_type_from_model(model)
        if payload.task_type and manifest_task_type and payload.task_type != manifest_task_type:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task type does not match model capability")
        resolved_task_type = payload.task_type or manifest_task_type

    buyer_tenant_id = asset.buyer_tenant_id
    if is_buyer_user(current_user.roles):
        buyer_tenant_id = current_user.tenant_id

    if not model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Model or pipeline resolution failed")
    if not resolved_task_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task type cannot be resolved")

    merged_policy = dict(DEFAULT_TASK_POLICY)
    merged_policy.update(payload.policy or {})
    # 将调度决策和编排配置固化到任务策略，便于边缘端可重放执行并保留审计上下文。
    # Persist scheduler/orchestrator metadata in task policy for reproducible edge execution.
    if scheduler_detail:
        merged_policy["master_scheduler"] = scheduler_detail
    if pipeline_payload:
        merged_policy["orchestrator"] = _build_orchestrator_policy(
            pipeline_payload=pipeline_payload,
            context={
                "scene_hint": payload.context.get("scene_hint") or asset.meta.get("use_case") if isinstance(asset.meta, dict) else None,
                "device_type": payload.context.get("device_type"),
                "camera_id": payload.context.get("camera_id"),
                "job_id": payload.context.get("job_id"),
                "timestamp": payload.context.get("timestamp"),
                **payload.context,
            },
            options=payload.options,
        )

    task = InferenceTask(
        id=str(uuid.uuid4()),
        model_id=model.id,
        pipeline_id=pipeline_id,
        asset_id=payload.asset_id,
        device_code=payload.device_code,
        task_type=resolved_task_type,
        status=TASK_STATUS_PENDING,
        buyer_tenant_id=buyer_tenant_id,
        policy=merged_policy,
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    db.add(task)
    db.commit()

    record_audit(
        db,
        action=actions.TASK_CREATE,
        resource_type="task",
        resource_id=task.id,
        detail={
            "pipeline_id": pipeline_id,
            "pipeline_code": pipeline_payload.get("pipeline_code") if pipeline_payload else None,
            "pipeline_version": pipeline_payload.get("version") if pipeline_payload else None,
            "model_id": model.id,
            "model_code": model.model_code,
            "asset_id": payload.asset_id,
            "task_type": resolved_task_type,
            "device_code": payload.device_code,
            "policy": merged_policy,
            "use_master_scheduler": scheduler_enabled,
            "context": payload.context,
            "options": payload.options,
        },
        request=request,
        actor=current_user,
    )

    if scheduler_detail:
        record_audit(
            db,
            action=actions.TASK_ROUTE,
            resource_type="task",
            resource_id=task.id,
            detail={
                "asset_id": payload.asset_id,
                "device_code": payload.device_code,
                "scheduler": scheduler_detail,
            },
            request=request,
            actor=current_user,
        )

    return {
        "id": task.id,
        "status": task.status,
        "task_type": task.task_type,
        "pipeline_id": pipeline_id,
        "pipeline_code": pipeline_payload.get("pipeline_code") if pipeline_payload else None,
        "pipeline_version": pipeline_payload.get("version") if pipeline_payload else None,
        "model_id": model.id,
        "model_code": model.model_code,
        "device_code": task.device_code,
        "policy": task.policy,
        "scheduler": scheduler_detail,
    }


@router.get("/{task_id}")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TASK_READ_ROLES)),
):
    task = db.query(InferenceTask).filter(InferenceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if is_buyer_user(current_user.roles) and task.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    result_count = db.query(InferenceResult).filter(InferenceResult.task_id == task.id).count()
    model = db.query(ModelRecord).filter(ModelRecord.id == task.model_id).first() if task.model_id else None
    run = db.query(InferenceRun).filter(InferenceRun.task_id == task.id).order_by(InferenceRun.created_at.desc()).first()
    review_items = db.query(ReviewQueue).filter(ReviewQueue.task_id == task.id).order_by(ReviewQueue.created_at.desc()).limit(5).all()

    return {
        "id": task.id,
        "status": task.status,
        "task_type": task.task_type,
        "model_id": task.model_id,
        "pipeline_id": task.pipeline_id,
        "model_code": model.model_code if model else None,
        "asset_id": task.asset_id,
        "device_code": task.device_code,
        "policy": task.policy,
        "scheduler": (task.policy or {}).get("master_scheduler"),
        "orchestrator": (task.policy or {}).get("orchestrator"),
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "error_message": task.error_message,
        "result_count": result_count,
        "run": {
            "job_id": run.job_id,
            "pipeline_version": run.pipeline_version,
            "threshold_version": run.threshold_version,
            "input_hash": run.input_hash,
            "models_versions": run.models_versions,
            "timings": run.timings,
            "result_summary": run.result_summary,
            "audit_hash": run.audit_hash,
        }
        if run
        else None,
        "review_queue": [
            {
                "reason": row.reason,
                "status": row.status,
                "assigned_to": row.assigned_to,
                "label_result": row.label_result,
                "created_at": row.created_at,
            }
            for row in review_items
        ],
    }


@router.get("")
def list_tasks(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TASK_READ_ROLES)),
):
    query = db.query(InferenceTask).order_by(InferenceTask.created_at.desc())
    if is_buyer_user(current_user.roles):
        query = query.filter(InferenceTask.buyer_tenant_id == current_user.tenant_id)
    if status_filter:
        query = query.filter(InferenceTask.status == status_filter)
    tasks = query.limit(100).all()

    return [
        {
            "id": task.id,
            "status": task.status,
            "task_type": task.task_type,
            "model_id": task.model_id,
            "pipeline_id": task.pipeline_id,
            "device_code": task.device_code,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }
        for task in tasks
    ]


@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TASK_CREATE_ROLES)),
):
    task = db.query(InferenceTask).filter(InferenceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if is_buyer_user(current_user.roles) and task.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    db.delete(task)
    db.commit()

    record_audit(
        db,
        action=actions.TASK_DELETE,
        resource_type="task",
        resource_id=task_id,
        detail={},
        request=request,
        actor=current_user,
    )

    return {"deleted": True, "task_id": task_id}
