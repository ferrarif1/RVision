from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.ui_errors import raise_ui_error
from app.db.database import get_db
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import SETTINGS_VIEW_ROLES
from app.services.assistant_service import (
    build_assistant_plan,
    cancel_local_llm_download,
    get_local_llm_catalog,
    get_provider_modes,
    list_local_llm_download_jobs,
    start_local_llm_download,
)
from app.services.audit_service import record_audit

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantPlannerRequest(BaseModel):
    goal: str = Field(default="", description="要识别什么 / 你想达成什么目标")
    asset_ids: list[str] = Field(default_factory=list, description="可选资产编号")
    current_task_type: str | None = Field(default=None, description="显式任务类型")
    current_model_id: str | None = Field(default=None, description="显式模型编号")
    llm_mode: str = Field(default="disabled", description="disabled | api | local")
    llm_selection: dict = Field(default_factory=dict, description="当前选择的大模型信息")
    api_config: dict = Field(default_factory=dict, description="OpenAI 兼容 API 配置，只在本次规划时使用")


class LocalLlmDownloadRequest(BaseModel):
    repo_id: str
    display_name: str | None = None


@router.get("/provider-modes")
def get_assistant_provider_modes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = get_provider_modes()
    record_audit(
        db,
        action=actions.ASSISTANT_PLAN,
        resource_type="assistant_provider_modes",
        resource_id="catalog",
        detail={"generated_at": payload.get("generated_at")},
        request=request,
        actor=current_user,
    )
    return payload


@router.get("/local-models")
def get_assistant_local_models(
    request: Request,
    force_refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = get_local_llm_catalog(force_refresh=force_refresh)
    record_audit(
        db,
        action=actions.LLM_CATALOG_REFRESH if force_refresh else actions.ASSISTANT_PLAN,
        resource_type="assistant_local_models",
        resource_id="catalog",
        detail={"force_refresh": force_refresh, "refreshed_at": payload.get("refreshed_at")},
        request=request,
        actor=current_user,
    )
    return payload


@router.get("/local-models/download-jobs")
def get_assistant_local_model_download_jobs(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = {"generated_at": None, "jobs": list_local_llm_download_jobs()}
    record_audit(
        db,
        action=actions.ASSISTANT_PLAN,
        resource_type="assistant_local_models",
        resource_id="download_jobs",
        detail={"job_count": len(payload["jobs"])},
        request=request,
        actor=current_user,
    )
    return payload


@router.post("/local-models/download")
def start_assistant_local_model_download(
    payload: LocalLlmDownloadRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    repo_id = str(payload.repo_id or "").strip()
    if not repo_id:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "assistant_local_model_repo_required",
            "请先选择一版本地开源模型，再开始下载。",
            next_step="回到本地模型库，选择平台精选模型后再试。",
        )
    result = start_local_llm_download(repo_id=repo_id, display_name=payload.display_name)
    record_audit(
        db,
        action=actions.LLM_DOWNLOAD_REQUEST,
        resource_type="assistant_local_models",
        resource_id=repo_id,
        detail=result,
        request=request,
        actor=current_user,
    )
    return result


@router.post("/local-models/download-jobs/{job_id}/cancel")
def cancel_assistant_local_model_download(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    result = cancel_local_llm_download(job_id)
    record_audit(
        db,
        action=actions.LLM_DOWNLOAD_CANCEL,
        resource_type="assistant_local_models",
        resource_id=job_id,
        detail=result,
        request=request,
        actor=current_user,
    )
    return result


@router.post("/plan")
def create_assistant_plan(
    payload: AssistantPlannerRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    goal = str(payload.goal or "").strip()
    if not goal and not payload.asset_ids and not payload.current_task_type and not payload.current_model_id:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "assistant_goal_required",
            "请至少补充一个目标说明、资产编号、任务类型或模型编号，系统才能给出下一步引导。",
            next_step="回到智能引导页的“目标与资源”步骤，填写要识别什么或选择一条已有资产。",
        )
    result = build_assistant_plan(
        db,
        current_user,
        goal=goal,
        asset_ids=payload.asset_ids,
        current_task_type=payload.current_task_type,
        current_model_id=payload.current_model_id,
        llm_mode=payload.llm_mode,
        llm_selection=payload.llm_selection,
        api_config=payload.api_config,
    )
    record_audit(
        db,
        action=actions.ASSISTANT_PLAN,
        resource_type="assistant_plan",
        resource_id=result.get("inferred_task_type") or "generic",
        detail={
            "goal": goal,
            "asset_ids": payload.asset_ids,
            "current_task_type": payload.current_task_type,
            "current_model_id": payload.current_model_id,
            "llm_mode": payload.llm_mode,
            "primary_action": result.get("primary_action"),
        },
        request=request,
        actor=current_user,
    )
    return result
