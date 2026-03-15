from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.ui_errors import raise_ui_error
from app.db.database import get_db
from app.security.dependencies import AuthUser, get_current_user, require_roles
from app.security.roles import ROLE_PLATFORM_ADMIN, SETTINGS_VIEW_ROLES, has_any_role
from app.services.audit_service import record_audit
from app.services.assistant_service import (
    cancel_local_llm_download,
    delete_local_llm,
    get_local_llm_catalog,
    get_provider_modes,
    list_local_llm_download_jobs,
    start_local_llm_download,
)
from app.services.data_governance_service import (
    build_data_governance_preview,
    execute_cleanup_synthetic_runtime,
    execute_keep_demo_chain,
    execute_prune_ocr_exports,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class DataGovernanceRunRequest(BaseModel):
    action: str = Field(description="执行动作 / keep_demo_chain | cleanup_synthetic_runtime | prune_ocr_exports")
    keep_latest: int = Field(default=3, ge=1, le=20, description="保留多少版 OCR 导出历史 / Keep latest OCR export versions")
    note: str | None = Field(default=None, description="执行说明 / Optional operator note")


class LocalLlmDownloadRequest(BaseModel):
    repo_id: str
    display_name: str | None = None


def _serialize_governance_preview(*, keep_latest: int, can_execute: bool) -> dict:
    preview = build_data_governance_preview(keep_latest=keep_latest)
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "keep_latest": keep_latest,
        "can_execute": can_execute,
        "actions": [
            preview["keep_demo_chain"],
            preview["cleanup_synthetic_runtime"],
            preview["prune_ocr_exports"],
        ],
    }


@router.get("/data-governance")
def get_data_governance_preview(
    request: Request,
    keep_latest: int = Query(default=3, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    can_execute = has_any_role(current_user.roles, (ROLE_PLATFORM_ADMIN,))
    payload = _serialize_governance_preview(keep_latest=keep_latest, can_execute=can_execute)
    record_audit(
        db,
        action=actions.DATA_GOVERNANCE_PREVIEW,
        resource_type="data_governance",
        resource_id="preview",
        detail={"keep_latest": keep_latest},
        request=request,
        actor=current_user,
    )
    return payload


@router.post("/data-governance/run")
def run_data_governance_action(
    payload: DataGovernanceRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(ROLE_PLATFORM_ADMIN)),
):
    action = str(payload.action or "").strip()
    try:
        if action == "keep_demo_chain":
            result = execute_keep_demo_chain()
        elif action == "cleanup_synthetic_runtime":
            result = execute_cleanup_synthetic_runtime()
        elif action == "prune_ocr_exports":
            result = execute_prune_ocr_exports(keep_latest=payload.keep_latest)
        else:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "data_governance_action_invalid",
                "当前数据治理动作不受支持。",
                next_step="请刷新设置页后，重新选择系统提供的治理动作。",
                raw_detail={"action": action},
            )
    except Exception as exc:  # pragma: no cover - runtime safety
        raise_ui_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "data_governance_execute_failed",
            "数据治理执行失败，当前策略没有完整跑完。",
            next_step="请先回到“数据治理”查看预览，再重新执行；若持续失败，请检查脚本输出日志。",
            raw_detail={"action": action, "error": str(exc)},
        )

    detail = {
        "action": action,
        "keep_latest": payload.keep_latest,
        "note": payload.note,
        "result": result,
    }
    record_audit(
        db,
        action=actions.DATA_GOVERNANCE_EXECUTE,
        resource_type="data_governance",
        resource_id=action,
        detail=detail,
        request=request,
        actor=current_user,
    )
    return {
        "executed_at": datetime.utcnow().isoformat(),
        "action": action,
        "result": result,
    }


@router.get("/llm/provider-modes")
def get_settings_llm_provider_modes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = get_provider_modes()
    record_audit(
        db,
        action=actions.ASSISTANT_PLAN,
        resource_type="settings_llm",
        resource_id="provider_modes",
        detail={"generated_at": payload.get("generated_at")},
        request=request,
        actor=current_user,
    )
    return payload


@router.get("/llm/local-models")
def get_settings_llm_local_models(
    request: Request,
    force_refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = get_local_llm_catalog(force_refresh=force_refresh)
    record_audit(
        db,
        action=actions.LLM_CATALOG_REFRESH if force_refresh else actions.ASSISTANT_PLAN,
        resource_type="settings_llm",
        resource_id="local_models",
        detail={"force_refresh": force_refresh, "refreshed_at": payload.get("refreshed_at")},
        request=request,
        actor=current_user,
    )
    return payload


@router.get("/llm/download-jobs")
def get_settings_llm_download_jobs(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = {"generated_at": datetime.utcnow().isoformat(), "jobs": list_local_llm_download_jobs()}
    record_audit(
        db,
        action=actions.ASSISTANT_PLAN,
        resource_type="settings_llm",
        resource_id="download_jobs",
        detail={"job_count": len(payload["jobs"])},
        request=request,
        actor=current_user,
    )
    return payload


@router.post("/llm/download")
def start_settings_llm_download(
    payload: LocalLlmDownloadRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    repo_id = str(payload.repo_id or "").strip()
    if not repo_id:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "settings_llm_repo_required",
            "请先选择一版本地模型，再开始下载。",
            next_step="回到设置页的大模型与下载，先在本地模型列表里选择一版模型。",
        )
    result = start_local_llm_download(repo_id=repo_id, display_name=payload.display_name)
    record_audit(
        db,
        action=actions.LLM_DOWNLOAD_REQUEST,
        resource_type="settings_llm",
        resource_id=repo_id,
        detail=result,
        request=request,
        actor=current_user,
    )
    return result


@router.post("/llm/download-jobs/{job_id}/cancel")
def cancel_settings_llm_download(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    result = cancel_local_llm_download(job_id)
    record_audit(
        db,
        action=actions.LLM_DOWNLOAD_CANCEL,
        resource_type="settings_llm",
        resource_id=job_id,
        detail=result,
        request=request,
        actor=current_user,
    )
    return result


@router.delete("/llm/local-models/{repo_id:path}")
def delete_settings_llm_local_model(
    repo_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    normalized_repo_id = str(repo_id or "").strip()
    if not normalized_repo_id:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "settings_llm_repo_required",
            "请先指定要删除的本地模型。",
            next_step="回到设置页的大模型与下载，从已下载模型里选择一条记录删除。",
        )
    result = delete_local_llm(normalized_repo_id)
    record_audit(
        db,
        action=actions.LLM_LOCAL_DELETE,
        resource_type="settings_llm",
        resource_id=normalized_repo_id,
        detail=result,
        request=request,
        actor=current_user,
    )
    return result
