import uuid
from datetime import datetime
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import TASK_STATUS_FAILED
from app.core.constants import TASK_STATUS_PENDING
from app.core.constants import TASK_STATUS_SUCCEEDED
from app.core.ui_errors import raise_ui_error
from app.db.database import get_db
from app.db.models import DataAsset, InferenceResult, InferenceRun, InferenceTask, ModelRecord, ModelRelease, ReviewQueue
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import TASK_CREATE_ROLES, TASK_READ_ROLES, is_buyer_user
from app.services.audit_service import record_audit
from app.services.model_router_service import TASK_TYPE_LABELS, latest_schedulable_models_by_task_type, recommend_small_models, task_type_from_model
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
PREFLIGHT_TASK_TYPES = ("object_detect", "car_number_ocr", "bolt_missing_detect")


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
    task_type: str | None = Field(default=None, description="任务类型 / Task type such as object_detect, car_number_ocr, bolt_missing_detect")
    device_code: str | None = Field(default=None, description="目标设备编码 / Target edge device code")
    policy: dict[str, Any] = Field(default_factory=dict, description="执行策略 / Execution policy overrides")
    use_master_scheduler: bool = Field(default=False, description="是否启用主调度器 / Enable master scheduler when model is not fixed")
    intent_text: str | None = Field(default=None, description="业务意图文本 / Free text intent for scheduler")
    context: dict[str, Any] = Field(default_factory=dict, description="上下文参数 / Runtime context, e.g. camera_id/scene_hint")
    options: dict[str, Any] = Field(default_factory=dict, description="运行选项 / Runtime options for pipeline/plugins")


class TaskPreflightInspectRequest(BaseModel):
    asset_id: str = Field(description="资产ID / Asset ID to inspect")
    device_code: str | None = Field(default=None, description="目标设备编码 / Edge device code")
    prompt_hint: str | None = Field(default=None, description="可选提示词 / Optional user-provided prompt hint")
    task_types: list[str] = Field(default_factory=list, description="预检任务类型范围 / Optional task type shortlist")
    wait_timeout_seconds: int = Field(default=25, ge=5, le=90, description="等待预检完成秒数 / Timeout in seconds")


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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "asset_not_found",
            "资源不存在，或当前账号无权访问这个资源。",
            next_step="请回到资源中心刷新列表，或重新上传图片/视频后再创建任务。",
        )

    if is_buyer_user(current_user.roles):
        if not current_user.tenant_id:
            raise_ui_error(
                status.HTTP_403_FORBIDDEN,
                "buyer_tenant_missing",
                "当前买方账号缺少租户上下文，暂时不能创建任务。",
                next_step="请重新登录；如果问题持续存在，再检查当前账号是否绑定了买方租户。",
            )
        if asset.buyer_tenant_id != current_user.tenant_id:
            raise_ui_error(
                status.HTTP_403_FORBIDDEN,
                "asset_out_of_scope",
                "这个资源不在当前买方租户范围内，不能直接用于任务执行。",
                next_step="请改选当前租户下的资源，或使用有权限的账号重试。",
            )
    return asset


def _ensure_inference_ready_asset(asset: DataAsset) -> None:
    if asset.asset_type == "archive":
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "archive_asset_not_supported_for_inference",
            "ZIP 数据集包不能直接做在线识别任务。",
            next_step="请改选单图、视频，或从已有推理资产里选择一条资源。",
        )


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


def _is_internal_task(task: InferenceTask) -> bool:
    policy = task.policy if isinstance(task.policy, dict) else {}
    return bool(policy.get("internal_kind"))


def _create_direct_task(
    *,
    db: Session,
    current_user: AuthUser,
    asset: DataAsset,
    model: ModelRecord,
    task_type: str,
    device_code: str | None,
    policy_overrides: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> InferenceTask:
    buyer_tenant_id = asset.buyer_tenant_id
    if is_buyer_user(current_user.roles):
        buyer_tenant_id = current_user.tenant_id
    merged_policy = dict(DEFAULT_TASK_POLICY)
    merged_policy.update(policy_overrides or {})
    task = InferenceTask(
        id=str(uuid.uuid4()),
        model_id=model.id,
        pipeline_id=None,
        asset_id=asset.id,
        device_code=device_code,
        task_type=task_type,
        status=TASK_STATUS_PENDING,
        buyer_tenant_id=buyer_tenant_id,
        policy=merged_policy,
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    db.add(task)
    db.commit()
    return task


def _preflight_candidate_from_result(
    *,
    task: InferenceTask,
    model: ModelRecord,
    result: InferenceResult | None,
    prompt_hint: str | None,
) -> dict[str, Any]:
    prompt_text = str(prompt_hint or "").strip().lower()
    wants_car_number = any(keyword in prompt_text for keyword in ("车号", "车厢号", "车皮号", "编号", "号码", "number", "ocr"))
    wants_object = any(keyword in prompt_text for keyword in ("car", "person", "train", "bus", "目标", "检测", "框"))
    wants_bolt = any(keyword in prompt_text for keyword in ("bolt", "螺栓", "紧固件", "缺失"))
    if task.status == TASK_STATUS_FAILED:
        return {
            "task_id": task.id,
            "task_type": task.task_type,
            "task_type_label": TASK_TYPE_LABELS.get(task.task_type, task.task_type),
            "title": TASK_TYPE_LABELS.get(task.task_type, task.task_type),
            "score": 35 if task.task_type == "car_number_ocr" and wants_car_number else 5,
            "recommended_prompt": prompt_hint or task.task_type,
            "summary": task.error_message or "预检执行失败",
            "matched_labels": [],
            "recognized_texts": [],
            "object_count": 0,
            "preview_result_id": result.id if result else None,
            "model": {
                "id": model.id,
                "model_code": model.model_code,
                "version": model.version,
            },
            "raw_summary": {},
            "status": task.status,
        }
    if task.status != TASK_STATUS_SUCCEEDED:
        return {
            "task_id": task.id,
            "task_type": task.task_type,
            "task_type_label": TASK_TYPE_LABELS.get(task.task_type, task.task_type),
            "title": TASK_TYPE_LABELS.get(task.task_type, task.task_type),
            "score": 25 if task.task_type == "car_number_ocr" and wants_car_number else 10,
            "recommended_prompt": prompt_hint or task.task_type,
            "summary": "预检仍在执行或尚未返回结果",
            "matched_labels": [],
            "recognized_texts": [],
            "object_count": 0,
            "preview_result_id": result.id if result else None,
            "model": {
                "id": model.id,
                "model_code": model.model_code,
                "version": model.version,
            },
            "raw_summary": {},
            "status": task.status,
        }
    result_json = result.result_json if result and isinstance(result.result_json, dict) else {}
    summary = result_json.get("summary") if isinstance(result_json.get("summary"), dict) else {}
    predictions = result_json.get("predictions") if isinstance(result_json.get("predictions"), list) else []
    matched_labels = [str(item).strip() for item in (result_json.get("matched_labels") or summary.get("matched_labels") or []) if str(item).strip()]
    recognized_texts = [
        str(item.get("text") or item.get("attributes", {}).get("text") or "").strip()
        for item in predictions
        if isinstance(item, dict)
    ]
    recognized_texts = [text for text in recognized_texts if text]
    if str(summary.get("car_number") or "").strip():
        recognized_texts.insert(0, str(summary.get("car_number")).strip())
    deduped_texts = list(dict.fromkeys(recognized_texts))

    score = 30
    title = TASK_TYPE_LABELS.get(task.task_type, task.task_type)
    recommended_prompt = prompt_hint or task.task_type
    recommendation_summary = "预检已完成，可按该任务类型继续识别。"

    if task.task_type == "car_number_ocr":
        if deduped_texts:
            score = 95
            title = "车号内容"
            recommended_prompt = "车号"
            recommendation_summary = f"预检已读出候选车号：{deduped_texts[0]}。建议直接走车号 OCR。"
        else:
            score = 60 if wants_car_number else 55
            title = "车号内容"
            recommended_prompt = "车号"
            recommendation_summary = "预检已跑过车号 OCR，但当前没有稳定文本，可继续复检。"
    elif task.task_type == "object_detect":
        if matched_labels:
            score = 88 if not wants_car_number else 72
            title = "目标框选"
            recommended_prompt = matched_labels[0]
            recommendation_summary = f"预检命中了目标标签：{', '.join(matched_labels[:4])}。建议按目标检测继续。"
        else:
            score = 40 if wants_object else 18
            title = "目标框选"
            recommended_prompt = prompt_hint or "car"
            recommendation_summary = "预检没有稳定命中标签，可按通用目标检测继续。"
    elif task.task_type == "bolt_missing_detect":
        missing = bool(summary.get("missing"))
        bolt_count = int(summary.get("bolt_count") or 0)
        score = 86 if missing else (70 if bolt_count else (42 if wants_bolt else 12))
        title = "螺栓缺失"
        recommended_prompt = "螺栓缺失"
        recommendation_summary = (
            "预检发现疑似螺栓缺失或异常，建议走螺栓缺失检测。"
            if missing
            else f"预检统计到 {bolt_count} 个螺栓候选，可继续做缺失检测。"
        )

    return {
        "task_id": task.id,
        "task_type": task.task_type,
        "task_type_label": TASK_TYPE_LABELS.get(task.task_type, task.task_type),
        "title": title,
        "score": score,
        "recommended_prompt": recommended_prompt,
        "summary": recommendation_summary,
        "matched_labels": matched_labels,
        "recognized_texts": deduped_texts,
        "object_count": int(result_json.get("object_count") or summary.get("object_count") or len(predictions) or 0),
        "preview_result_id": result.id if result else None,
        "model": {
            "id": model.id,
            "model_code": model.model_code,
            "version": model.version,
        },
        "raw_summary": summary,
        "status": task.status,
    }


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
    _ensure_inference_ready_asset(asset)
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


@router.post("/preflight-inspect")
def preflight_inspect_task_targets(
    payload: TaskPreflightInspectRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TASK_CREATE_ROLES)),
):
    asset = _get_asset_in_scope(db, payload.asset_id, current_user)
    _ensure_inference_ready_asset(asset)
    requested_types = {str(item or "").strip() for item in payload.task_types if str(item or "").strip()}
    effective_task_types = requested_types or set(PREFLIGHT_TASK_TYPES)
    latest_models = latest_schedulable_models_by_task_type(
        db,
        current_user,
        device_code=payload.device_code,
        task_types=effective_task_types,
    )
    if not latest_models:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No schedulable models available for preflight inspection")

    created_tasks: list[tuple[InferenceTask, ModelRecord]] = []
    for task_type in PREFLIGHT_TASK_TYPES:
        candidate = latest_models.get(task_type)
        if not candidate:
            continue
        model = db.query(ModelRecord).filter(ModelRecord.id == candidate.model_id).first()
        if not model:
            continue
        task = _create_direct_task(
            db=db,
            current_user=current_user,
            asset=asset,
            model=model,
            task_type=task_type,
            device_code=payload.device_code,
            policy_overrides={
                "internal_kind": "quick_detect_preflight",
                "preflight_inspect": True,
                "retention_days": 1,
                "quick_detect": {"stage": "preflight", "prompt_hint": payload.prompt_hint},
            },
            context={},
            options={},
        )
        created_tasks.append((task, model))

    deadline = time.time() + payload.wait_timeout_seconds
    pending_ids = {task.id for task, _ in created_tasks}
    while pending_ids and time.time() < deadline:
        rows = db.query(InferenceTask).filter(InferenceTask.id.in_(tuple(pending_ids))).all()
        for row in rows:
            if row.status in {TASK_STATUS_SUCCEEDED, TASK_STATUS_FAILED}:
                pending_ids.discard(row.id)
        if pending_ids:
            time.sleep(1.0)
            db.expire_all()

    completed_tasks = db.query(InferenceTask).filter(InferenceTask.id.in_([task.id for task, _ in created_tasks])).all()
    task_map = {task.id: task for task in completed_tasks}
    result_rows = db.query(InferenceResult).filter(InferenceResult.task_id.in_(tuple(task_map.keys()))).order_by(InferenceResult.created_at.asc()).all() if task_map else []
    result_map: dict[str, InferenceResult] = {}
    for row in result_rows:
        result_map[row.task_id] = row

    candidates = []
    for task, model in created_tasks:
        resolved_task = task_map.get(task.id, task)
        candidates.append(
            _preflight_candidate_from_result(
                task=resolved_task,
                model=model,
                result=result_map.get(task.id),
                prompt_hint=payload.prompt_hint,
            )
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)

    record_audit(
        db,
        action=actions.TASK_ROUTE,
        resource_type="asset",
        resource_id=asset.id,
        detail={
            "asset_id": asset.id,
            "device_code": payload.device_code,
            "prompt_hint": payload.prompt_hint,
            "preflight_candidates": candidates,
        },
        request=request,
        actor=current_user,
    )

    return {
        "asset_id": asset.id,
        "device_code": payload.device_code,
        "prompt_hint": payload.prompt_hint,
        "timed_out": bool(pending_ids),
        "candidates": candidates,
        "selected_candidate": candidates[0] if candidates else None,
        "created_task_ids": [task.id for task, _ in created_tasks],
    }


@router.post("/create")
def create_task(
    payload: TaskCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TASK_CREATE_ROLES)),
):
    asset = _get_asset_in_scope(db, payload.asset_id, current_user)
    _ensure_inference_ready_asset(asset)
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
            raise_ui_error(
                status.HTTP_404_NOT_FOUND,
                "no_schedulable_model",
                "当前没有可调度的模型，系统没法替你自动选模。",
                next_step="请先发布一版可用模型，或在任务中心显式选择具体模型后再试。",
            )
        model = db.query(ModelRecord).filter(ModelRecord.id == selected_model["model_id"]).first()
        if not model:
            raise_ui_error(
                status.HTTP_404_NOT_FOUND,
                "scheduled_model_missing",
                "系统推荐的模型记录已不存在或不可见。",
                next_step="请刷新模型列表后重新创建任务；如果持续出现，检查模型数据是否被清理。",
            )
        resolved_task_type = decision.get("inferred_task_type") or selected_model.get("task_type")
        scheduler_detail = _build_scheduler_detail(decision, payload.intent_text)
    elif not payload.pipeline_id:
        model = db.query(ModelRecord).filter(ModelRecord.id == payload.model_id).first()
        if not model:
            raise_ui_error(
                status.HTTP_404_NOT_FOUND,
                "model_not_found",
                "所选模型不存在，或当前账号看不到这版模型。",
                next_step="请重新选择一版模型，或回到模型中心确认这版模型是否还在。",
            )

        if is_buyer_user(current_user.roles):
            if not _is_model_released_to_buyer(db, model.id, current_user.tenant_code, payload.device_code):
                raise_ui_error(
                    status.HTTP_403_FORBIDDEN,
                    "model_not_released_to_scope",
                    "这版模型还没有授权给当前租户或目标设备。",
                    next_step="请先发布到当前买方/设备，或改选一版已经发布可用的模型。",
                )

        manifest_task_type = task_type_from_model(model)
        if payload.task_type and manifest_task_type and payload.task_type != manifest_task_type:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "task_type_model_capability_mismatch",
                "当前任务类型和所选模型能力不匹配。",
                next_step="请改选同任务类型的模型，或把任务类型切回模型支持的能力。",
            )
        resolved_task_type = payload.task_type or manifest_task_type

    buyer_tenant_id = asset.buyer_tenant_id
    if is_buyer_user(current_user.roles):
        buyer_tenant_id = current_user.tenant_id

    if not model:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "model_or_pipeline_resolution_failed",
            "任务没有解析到可执行的模型或流水线。",
            next_step="请检查是否已选模型/流水线、是否已发布，以及任务类型是否明确。",
        )
    if not resolved_task_type:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "task_type_unresolved",
            "系统没能判断当前任务应该按哪类能力执行。",
            next_step="请明确填写识别目标，或直接选择一版具体模型后重试。",
        )

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
    include_internal: bool = Query(default=False, description="是否包含内部预检任务 / Include internal preflight tasks"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*TASK_READ_ROLES)),
):
    query = db.query(InferenceTask).order_by(InferenceTask.created_at.desc())
    if is_buyer_user(current_user.roles):
        query = query.filter(InferenceTask.buyer_tenant_id == current_user.tenant_id)
    if status_filter:
        query = query.filter(InferenceTask.status == status_filter)
    tasks = query.limit(100).all()
    if not include_internal:
        tasks = [task for task in tasks if not _is_internal_task(task)]

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
