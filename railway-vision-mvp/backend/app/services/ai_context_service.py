from __future__ import annotations

from typing import Any

from app.services.ai_settings_service import get_ai_behavior_settings, list_ai_knowledge_documents, get_ai_knowledge_document


def normalize_workflow_scope(workflow_path: str | None, action_id: str | None = None) -> str:
    path = str(workflow_path or "").strip()
    action = str(action_id or "").strip()
    if "/upload" in path or action == "upload_or_select_assets":
        return "upload"
    if "/train" in path or action in {"prepare_training_data", "open_training_path"}:
        return "train"
    if "/deploy" in path or action in {"open_approval_workbench", "open_release_workbench"}:
        return "deploy"
    if "/results" in path or action == "validate_existing_model":
        return "results"
    if "/troubleshoot" in path:
        return "troubleshoot"
    return "global"


def _doc_matches_scope(scope_rows: list[str], workflow_scope: str) -> bool:
    normalized = [str(item or "").strip() for item in scope_rows if str(item or "").strip()]
    if not normalized or "global" in normalized:
        return True
    return workflow_scope in normalized


def assemble_ai_context(*, workflow_scope: str = "global", task_type: str | None = None, goal: str = "") -> dict[str, Any]:
    behavior = get_ai_behavior_settings()
    doc_rows = list_ai_knowledge_documents().get("documents") or []
    active_docs: list[dict[str, Any]] = []
    excerpts: list[str] = []
    for row in doc_rows:
        if not row.get("enabled"):
            continue
        if not _doc_matches_scope(row.get("scope") or [], workflow_scope):
            continue
        full = get_ai_knowledge_document(str(row.get("id") or "")) or {}
        content = str(full.get("content") or "").strip()
        excerpt = content[:1800]
        active_docs.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "scope": row.get("scope") or ["global"],
                "source_type": row.get("source_type") or "custom",
                "updated_at": full.get("updated_at") or row.get("updated_at"),
                "excerpt": excerpt,
            }
        )
        if excerpt:
            excerpts.append(f"[{row.get('title')}]\n{excerpt}")
    system_prompt_parts = [str(behavior.get("system_prompt") or "").strip()]
    system_prompt_parts.append("请只基于当前产品真实能力给建议，并明确区分 AI Workspace 与 Expert Console。")
    if behavior.get("strict_document_mode"):
        system_prompt_parts.append("严格按系统文档和已知能力边界回答，不要编造不存在的功能。")
    if behavior.get("prefer_workflow_jump"):
        system_prompt_parts.append("优先给出 workflow 路径，而不是只输出说明。")
    if task_type:
        system_prompt_parts.append(f"当前推断任务类型：{task_type}。")
    if goal:
        system_prompt_parts.append(f"当前用户目标：{goal}。")
    if excerpts:
        system_prompt_parts.append("以下是当前启用的系统上下文文档摘录：\n\n" + "\n\n".join(excerpts[:4]))
    return {
        "workflow_scope": workflow_scope,
        "behavior": behavior,
        "documents": active_docs,
        "system_prompt": "\n\n".join(part for part in system_prompt_parts if part),
    }
