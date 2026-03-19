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
    activate_local_llm,
    cancel_local_llm_download,
    delete_local_llm,
    get_local_llm_folder_info,
    get_local_llm_catalog,
    get_local_llm_runtime_status,
    get_provider_modes,
    list_local_llm_download_jobs,
    start_local_llm_download,
)
from app.services.ai_provider_service import test_provider_connection
from app.services.ai_settings_service import (
    delete_ai_knowledge_document,
    delete_ai_provider_config,
    get_ai_behavior_settings,
    get_ai_knowledge_document,
    get_default_ai_provider,
    get_ai_provider_config,
    list_ai_knowledge_documents,
    list_ai_provider_configs,
    record_ai_provider_test_result,
    set_default_ai_provider,
    upsert_ai_knowledge_document,
    upsert_ai_provider_config,
    update_ai_behavior_settings,
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


class AIProviderConfigRequest(BaseModel):
    id: str | None = None
    name: str
    provider: str = "openai_compatible"
    mode: str = "api"
    base_url: str = ""
    api_path: str = "/v1"
    model_name: str = ""
    format_type: str = "openai_compatible"
    api_key: str = ""
    organization: str = ""
    project: str = ""
    enable_stream: bool = False
    timeout: int = 45
    temperature: float = 0.2
    max_tokens: int = 900
    enabled: bool = True
    is_default: bool = False
    scope: list[str] = Field(default_factory=lambda: ["global"])


class AIKnowledgeDocumentRequest(BaseModel):
    id: str | None = None
    title: str
    description: str = ""
    content: str = ""
    enabled: bool = True
    scope: list[str] = Field(default_factory=lambda: ["global"])


class AIBehaviorSettingsRequest(BaseModel):
    system_prompt: str = ""
    strict_document_mode: bool = True
    allow_freeform_suggestions: bool = False
    prefer_workflow_jump: bool = True
    show_reasoning_summary: bool = True
    allow_auto_prefill: bool = True


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


@router.get("/llm/local-runtime")
def get_settings_llm_local_runtime(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = get_local_llm_runtime_status()
    record_audit(
        db,
        action=actions.ASSISTANT_PLAN,
        resource_type="settings_llm",
        resource_id="local_runtime",
        detail={"ok": payload.get("ok"), "base_url": payload.get("base_url"), "model_count": payload.get("model_count")},
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


@router.post("/llm/local-models/{repo_id:path}/open-folder")
def open_settings_llm_local_model_folder(
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
            "请先指定要打开目录的本地模型。",
            next_step="回到设置页的大模型与下载，从已下载模型里选择一条记录。",
        )
    result = get_local_llm_folder_info(normalized_repo_id)
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_llm",
        resource_id=normalized_repo_id,
        detail={"action": "open_local_model_folder", **result},
        request=request,
        actor=current_user,
    )
    return result


@router.post("/llm/local-models/{repo_id:path}/activate")
def activate_settings_llm_local_model(
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
            "请先指定要接入的本地模型。",
            next_step="回到设置页的大模型与下载，从已下载模型里选择一条记录后重新接入。",
        )
    try:
        result = activate_local_llm(normalized_repo_id)
    except FileNotFoundError:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "settings_llm_local_model_missing",
            "当前本地模型快照还没准备好，暂时不能接入对话。",
            next_step="请先等待下载完成，再重新点击“接入对话”。",
            raw_detail={"repo_id": normalized_repo_id},
        )
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_llm",
        resource_id=normalized_repo_id,
        detail={"action": "activate_local_model", **result},
        request=request,
        actor=current_user,
    )
    return result


@router.get("/ai/providers")
def get_settings_ai_providers(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = list_ai_provider_configs()
    payload["default_provider"] = get_default_ai_provider()
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_ai",
        resource_id="providers_list",
        detail={"count": len(payload.get("providers") or [])},
        request=request,
        actor=current_user,
    )
    return payload


@router.post("/ai/providers")
def create_settings_ai_provider(
    payload: AIProviderConfigRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    result = upsert_ai_provider_config(payload.model_dump())
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_ai",
        resource_id=result.get("id") or "provider",
        detail={"action": "create_or_update_provider", "mode": result.get("mode"), "provider": result.get("provider")},
        request=request,
        actor=current_user,
    )
    return result


@router.put("/ai/providers/{provider_id}")
def update_settings_ai_provider(
    provider_id: str,
    payload: AIProviderConfigRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    body = payload.model_dump()
    body["id"] = provider_id
    result = upsert_ai_provider_config(body)
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_ai",
        resource_id=provider_id,
        detail={"action": "update_provider", "mode": result.get("mode"), "provider": result.get("provider")},
        request=request,
        actor=current_user,
    )
    return result


@router.delete("/ai/providers/{provider_id}")
def delete_settings_ai_provider(
    provider_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    result = delete_ai_provider_config(provider_id)
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_ai",
        resource_id=provider_id,
        detail={"action": "delete_provider", "removed": result.get("removed")},
        request=request,
        actor=current_user,
    )
    return result


@router.post("/ai/providers/{provider_id}/default")
def set_settings_ai_provider_default(
    provider_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    try:
        result = set_default_ai_provider(provider_id)
    except KeyError:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "settings_ai_provider_not_found",
            "找不到要设为默认的大模型配置。",
            next_step="请刷新设置页后重试。",
        )
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_ai",
        resource_id=provider_id,
        detail={"action": "set_default_provider"},
        request=request,
        actor=current_user,
    )
    return result


@router.post("/ai/providers/test")
def test_settings_ai_provider(
    payload: AIProviderConfigRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    try:
        result = test_provider_connection(payload.model_dump())
    except Exception as exc:
        result = {
            "ok": False,
            "message": f"连接测试失败：{exc}",
            "tested_at": datetime.utcnow().isoformat(),
        }
    if payload.id:
        record_ai_provider_test_result(payload.id, result)
    record_audit(
        db,
        action=actions.AI_PROVIDER_TEST,
        resource_type="settings_ai",
        resource_id=str(payload.id or payload.name or "provider_test"),
        detail={"ok": result.get("ok"), "message": result.get("message")},
        request=request,
        actor=current_user,
    )
    return result


@router.get("/ai/knowledge")
def get_settings_ai_knowledge(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = list_ai_knowledge_documents()
    record_audit(
        db,
        action=actions.AI_KNOWLEDGE_UPDATE,
        resource_type="settings_ai",
        resource_id="knowledge_list",
        detail={"count": len(payload.get("documents") or [])},
        request=request,
        actor=current_user,
    )
    return payload


@router.get("/ai/knowledge/{doc_id}")
def get_settings_ai_knowledge_document(
    doc_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    result = get_ai_knowledge_document(doc_id)
    if not result:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "settings_ai_knowledge_not_found",
            "找不到这份 AI 系统文档。",
            next_step="请刷新列表后重新选择。",
        )
    record_audit(
        db,
        action=actions.AI_KNOWLEDGE_UPDATE,
        resource_type="settings_ai",
        resource_id=doc_id,
        detail={"action": "preview_document"},
        request=request,
        actor=current_user,
    )
    return result


@router.post("/ai/knowledge")
def create_settings_ai_knowledge_document(
    payload: AIKnowledgeDocumentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    result = upsert_ai_knowledge_document(payload.model_dump())
    record_audit(
        db,
        action=actions.AI_KNOWLEDGE_UPDATE,
        resource_type="settings_ai",
        resource_id=result.get("id") or "knowledge_document",
        detail={"action": "create_or_update_document", "source_type": result.get("source_type")},
        request=request,
        actor=current_user,
    )
    return result


@router.put("/ai/knowledge/{doc_id}")
def update_settings_ai_knowledge_document(
    doc_id: str,
    payload: AIKnowledgeDocumentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    body = payload.model_dump()
    body["id"] = doc_id
    result = upsert_ai_knowledge_document(body)
    record_audit(
        db,
        action=actions.AI_KNOWLEDGE_UPDATE,
        resource_type="settings_ai",
        resource_id=doc_id,
        detail={"action": "update_document", "source_type": result.get("source_type")},
        request=request,
        actor=current_user,
    )
    return result


@router.delete("/ai/knowledge/{doc_id}")
def delete_settings_ai_knowledge_document(
    doc_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    result = delete_ai_knowledge_document(doc_id)
    record_audit(
        db,
        action=actions.AI_KNOWLEDGE_UPDATE,
        resource_type="settings_ai",
        resource_id=doc_id,
        detail={"action": "delete_document", "removed": result.get("removed")},
        request=request,
        actor=current_user,
    )
    return result


@router.get("/ai/behavior")
def get_settings_ai_behavior(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    payload = get_ai_behavior_settings()
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_ai",
        resource_id="behavior",
        detail={"action": "get_behavior"},
        request=request,
        actor=current_user,
    )
    return payload


@router.put("/ai/behavior")
def update_settings_ai_behavior(
    payload: AIBehaviorSettingsRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    result = update_ai_behavior_settings(payload.model_dump())
    record_audit(
        db,
        action=actions.AI_SETTINGS_UPDATE,
        resource_type="settings_ai",
        resource_id="behavior",
        detail={"action": "update_behavior"},
        request=request,
        actor=current_user,
    )
    return result
