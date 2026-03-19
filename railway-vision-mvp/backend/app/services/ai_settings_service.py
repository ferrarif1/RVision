from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re
from urllib.parse import urlparse, urlunparse

UTC = timezone.utc
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if not (PROJECT_ROOT / "docs").exists() and Path("/app/docs").exists():
    PROJECT_ROOT = Path("/app")
RUNTIME_ROOT = PROJECT_ROOT / ".runtime" / "ai_native"
SETTINGS_PATH = RUNTIME_ROOT / "settings.json"

BUILTIN_DOCUMENTS = [
    {
        "id": "system_overview",
        "title": "系统总览",
        "description": "告诉 AI 当前产品是什么、有哪些真实能力边界。",
        "path": PROJECT_ROOT / "docs" / "system_overview.md",
        "scope": ["global"],
        "enabled": True,
    },
    {
        "id": "capabilities",
        "title": "能力说明",
        "description": "告诉 AI 哪些能力真实可执行、哪些要跳专家页。",
        "path": PROJECT_ROOT / "docs" / "capabilities.md",
        "scope": ["global"],
        "enabled": True,
    },
    {
        "id": "workflows",
        "title": "Workflow 说明",
        "description": "告诉 AI upload/train/deploy/results/troubleshoot 应该怎么路由。",
        "path": PROJECT_ROOT / "docs" / "workflows.md",
        "scope": ["upload", "train", "deploy", "results", "troubleshoot"],
        "enabled": True,
    },
    {
        "id": "llm_operating_manual",
        "title": "LLM 工作手册",
        "description": "约束 AI 的输出风格、解释方式和承诺边界。",
        "path": PROJECT_ROOT / "docs" / "llm_operating_manual.md",
        "scope": ["global"],
        "enabled": True,
    },
]

DEFAULT_BEHAVIOR_SETTINGS = {
    "system_prompt": "你是 RVision 里的 AI 工作台助手。请根据真实系统能力给出下一步，不要承诺不存在的操作。",
    "strict_document_mode": True,
    "allow_freeform_suggestions": False,
    "prefer_workflow_jump": True,
    "show_reasoning_summary": True,
    "allow_auto_prefill": True,
    "updated_at": None,
}

DEFAULT_PROVIDER_SETTINGS = [
    {
        "id": "local-openai-compatible",
        "name": "本地 OpenAI 兼容服务",
        "provider": "local_openai_compatible",
        "mode": "local",
        "base_url": "",
        "api_path": "/v1",
        "model_name": "",
        "format_type": "openai_compatible",
        "api_key": "",
        "organization": "",
        "project": "",
        "enable_stream": True,
        "timeout": 45,
        "temperature": 0.2,
        "max_tokens": 900,
        "enabled": False,
        "is_default": False,
        "scope": ["global"],
        "created_at": None,
        "updated_at": None,
        "last_test_result": None,
    },
    {
        "id": "openai-compatible-api",
        "name": "远程 OpenAI 兼容 API",
        "provider": "openai_compatible",
        "mode": "api",
        "base_url": "",
        "api_path": "/v1",
        "model_name": "",
        "format_type": "openai_compatible",
        "api_key": "",
        "organization": "",
        "project": "",
        "enable_stream": False,
        "timeout": 45,
        "temperature": 0.2,
        "max_tokens": 900,
        "enabled": False,
        "is_default": False,
        "scope": ["global"],
        "created_at": None,
        "updated_at": None,
        "last_test_result": None,
    },
]


def _running_in_container() -> bool:
    return Path("/.dockerenv").exists() or Path("/app").exists()


def _default_local_base_url() -> str:
    return "http://host.docker.internal:11434" if _running_in_container() else "http://127.0.0.1:11434"


def _normalize_local_base_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
      return _default_local_base_url()
    try:
      parsed = urlparse(raw)
    except Exception:
      return raw
    host = str(parsed.hostname or "").strip().lower()
    if not _running_in_container() or host not in {"127.0.0.1", "localhost"}:
      return raw
    netloc = parsed.netloc
    if "@" in netloc:
      auth, hostport = netloc.rsplit("@", 1)
      host_bits = hostport.split(":")
      port = host_bits[1] if len(host_bits) > 1 else str(parsed.port or 11434)
      new_netloc = f"{auth}@host.docker.internal:{port}"
    else:
      port = str(parsed.port or 11434)
      new_netloc = f"host.docker.internal:{port}"
    return urlunparse(parsed._replace(netloc=new_netloc))


def _provider_slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return clean or f"provider-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_runtime_dir() -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)


def _json_load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_runtime_dir()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_state() -> dict[str, Any]:
    return {
        "providers": [dict(item) for item in DEFAULT_PROVIDER_SETTINGS],
        "documents": [],
        "behavior": dict(DEFAULT_BEHAVIOR_SETTINGS),
        "updated_at": None,
    }


def _normalize_scope(value: Any) -> list[str]:
    if isinstance(value, str):
        rows = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        rows = [str(part).strip() for part in value if str(part).strip()]
    else:
        rows = []
    return rows or ["global"]


def _normalize_provider(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or {})
    now = _now_iso()
    provider_id = str(payload.get("id") or base.get("id") or f"provider-{uuid.uuid4().hex[:10]}").strip()
    base.update(
        {
            "id": provider_id,
            "name": str(payload.get("name") or base.get("name") or provider_id).strip(),
            "provider": str(payload.get("provider") or base.get("provider") or "openai_compatible").strip(),
            "mode": str(payload.get("mode") or base.get("mode") or "api").strip() or "api",
            "base_url": str(payload.get("base_url") or base.get("base_url") or "").strip(),
            "api_path": str(payload.get("api_path") or base.get("api_path") or "/v1").strip() or "/v1",
            "model_name": str(payload.get("model_name") or base.get("model_name") or "").strip(),
            "format_type": str(payload.get("format_type") or base.get("format_type") or "openai_compatible").strip() or "openai_compatible",
            "organization": str(payload.get("organization") or base.get("organization") or "").strip(),
            "project": str(payload.get("project") or base.get("project") or "").strip(),
            "enable_stream": bool(payload.get("enable_stream") if "enable_stream" in payload else base.get("enable_stream", False)),
            "timeout": max(5, min(300, int(payload.get("timeout") or base.get("timeout") or 45))),
            "temperature": float(payload.get("temperature") if payload.get("temperature") is not None else base.get("temperature") or 0.2),
            "max_tokens": max(64, min(8192, int(payload.get("max_tokens") or base.get("max_tokens") or 900))),
            "enabled": bool(payload.get("enabled") if "enabled" in payload else base.get("enabled", True)),
            "is_default": bool(payload.get("is_default") if "is_default" in payload else base.get("is_default", False)),
            "scope": _normalize_scope(payload.get("scope") if "scope" in payload else base.get("scope")),
            "created_at": base.get("created_at") or now,
            "updated_at": now,
            "last_test_result": base.get("last_test_result"),
        }
    )
    if "api_key" in payload:
        base["api_key"] = str(payload.get("api_key") or "").strip()
    else:
        base["api_key"] = str(base.get("api_key") or "").strip()
    if str(base.get("mode") or "") == "local" or str(base.get("provider") or "") == "local_openai_compatible":
        base["base_url"] = _normalize_local_base_url(base.get("base_url"))
    return base


def _normalize_custom_document(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or {})
    now = _now_iso()
    doc_id = str(payload.get("id") or base.get("id") or f"custom-doc-{uuid.uuid4().hex[:10]}").strip()
    base.update(
        {
            "id": doc_id,
            "title": str(payload.get("title") or base.get("title") or doc_id).strip(),
            "description": str(payload.get("description") or base.get("description") or "").strip(),
            "content": str(payload.get("content") or base.get("content") or "").strip(),
            "scope": _normalize_scope(payload.get("scope") if "scope" in payload else base.get("scope")),
            "enabled": bool(payload.get("enabled") if "enabled" in payload else base.get("enabled", True)),
            "source_type": "custom",
            "created_at": base.get("created_at") or now,
            "updated_at": now,
        }
    )
    return base


def load_ai_settings_state() -> dict[str, Any]:
    payload = _default_state()
    if SETTINGS_PATH.exists():
        stored = _json_load(SETTINGS_PATH)
        providers = stored.get("providers") if isinstance(stored.get("providers"), list) else []
        documents = stored.get("documents") if isinstance(stored.get("documents"), list) else []
        behavior = stored.get("behavior") if isinstance(stored.get("behavior"), dict) else {}
        payload["providers"] = [dict(item) for item in providers if isinstance(item, dict)] or payload["providers"]
        payload["documents"] = [dict(item) for item in documents if isinstance(item, dict)]
        payload["behavior"].update(behavior)
        payload["updated_at"] = stored.get("updated_at")
    migrated = False
    normalized_providers: list[dict[str, Any]] = []
    for item in payload.get("providers") or []:
        row = dict(item)
        if str(row.get("mode") or "") == "local" or str(row.get("provider") or "") == "local_openai_compatible":
            next_base_url = _normalize_local_base_url(row.get("base_url"))
            if next_base_url != str(row.get("base_url") or "").strip():
                row["base_url"] = next_base_url
                migrated = True
        normalized_providers.append(row)
    payload["providers"] = normalized_providers
    if migrated:
        save_ai_settings_state(payload)
    return payload


def save_ai_settings_state(state: dict[str, Any]) -> dict[str, Any]:
    next_state = dict(state)
    next_state["updated_at"] = _now_iso()
    _write_json(SETTINGS_PATH, next_state)
    return next_state


def _mask_provider(provider: dict[str, Any]) -> dict[str, Any]:
    row = dict(provider)
    api_key = str(row.get("api_key") or "")
    row["has_api_key"] = bool(api_key)
    row["api_key_mask"] = f"***{api_key[-4:]}" if len(api_key) >= 4 else ("***" if api_key else "")
    row.pop("api_key", None)
    return row


def list_ai_provider_configs() -> dict[str, Any]:
    state = load_ai_settings_state()
    providers = state.get("providers") or []
    return {
        "generated_at": _now_iso(),
        "providers": [_mask_provider(item) for item in providers],
    }


def get_ai_provider_config(provider_id: str, *, include_secret: bool = False) -> dict[str, Any] | None:
    state = load_ai_settings_state()
    for item in state.get("providers") or []:
        if str(item.get("id") or "").strip() == str(provider_id or "").strip():
            return dict(item) if include_secret else _mask_provider(item)
    return None


def upsert_ai_provider_config(payload: dict[str, Any]) -> dict[str, Any]:
    state = load_ai_settings_state()
    providers = [dict(item) for item in state.get("providers") or []]
    normalized_id = str(payload.get("id") or "").strip()
    existing = next((item for item in providers if str(item.get("id") or "") == normalized_id), None)
    normalized = _normalize_provider(payload, existing)
    next_providers = [item for item in providers if str(item.get("id") or "") != normalized["id"]]
    if normalized.get("is_default"):
        for item in next_providers:
            item["is_default"] = False
    next_providers.append(normalized)
    if not any(item.get("is_default") for item in next_providers) and next_providers:
        next_providers[0]["is_default"] = True
    state["providers"] = next_providers
    save_ai_settings_state(state)
    return _mask_provider(normalized)


def upsert_local_llm_provider(
    *,
    repo_id: str,
    display_name: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    api_path: str | None = None,
    scope: list[str] | None = None,
) -> dict[str, Any]:
    normalized_repo = str(repo_id or "").strip()
    if not normalized_repo:
        raise ValueError("repo_id is required")
    state = load_ai_settings_state()
    providers = [dict(item) for item in state.get("providers") or []]
    provider_id = f"local-llm-{_provider_slug(normalized_repo)}"
    existing = next((item for item in providers if str(item.get("id") or "") == provider_id), None)
    local_template = next(
        (item for item in providers if str(item.get("provider") or "") == "local_openai_compatible"),
        next((item for item in DEFAULT_PROVIDER_SETTINGS if str(item.get("provider") or "") == "local_openai_compatible"), {}),
    )
    payload = {
        "id": provider_id,
        "name": str(display_name or normalized_repo).strip() or normalized_repo,
        "provider": "local_openai_compatible",
        "mode": "local",
        "base_url": str(base_url or (existing or {}).get("base_url") or local_template.get("base_url") or "http://127.0.0.1:11434").strip(),
        "api_path": str(api_path or (existing or {}).get("api_path") or local_template.get("api_path") or "/v1").strip() or "/v1",
        "model_name": str(model_name or normalized_repo).strip() or normalized_repo,
        "format_type": "openai_compatible",
        "api_key": str((existing or {}).get("api_key") or local_template.get("api_key") or "").strip(),
        "organization": str((existing or {}).get("organization") or local_template.get("organization") or "").strip(),
        "project": str((existing or {}).get("project") or local_template.get("project") or "").strip(),
        "enable_stream": bool((existing or {}).get("enable_stream", local_template.get("enable_stream", True))),
        "timeout": int((existing or {}).get("timeout") or local_template.get("timeout") or 45),
        "temperature": float((existing or {}).get("temperature") or local_template.get("temperature") or 0.2),
        "max_tokens": int((existing or {}).get("max_tokens") or local_template.get("max_tokens") or 900),
        "enabled": True,
        "is_default": True,
        "scope": _normalize_scope(scope or (existing or {}).get("scope") or ["global"]),
    }
    normalized = _normalize_provider(payload, existing)
    next_providers = []
    for item in providers:
        row = dict(item)
        row["is_default"] = False
        next_providers.append(row)
    next_providers = [item for item in next_providers if str(item.get("id") or "") != provider_id]
    next_providers.append(normalized)
    state["providers"] = next_providers
    save_ai_settings_state(state)
    return dict(normalized)


def delete_ai_provider_config(provider_id: str) -> dict[str, Any]:
    state = load_ai_settings_state()
    providers = [dict(item) for item in state.get("providers") or []]
    removed = next((item for item in providers if str(item.get("id") or "") == str(provider_id or "").strip()), None)
    state["providers"] = [item for item in providers if str(item.get("id") or "") != str(provider_id or "").strip()]
    if state["providers"] and not any(item.get("is_default") for item in state["providers"]):
        state["providers"][0]["is_default"] = True
    save_ai_settings_state(state)
    return {
        "provider_id": str(provider_id or "").strip(),
        "removed": bool(removed),
        "deleted_at": _now_iso(),
    }


def set_default_ai_provider(provider_id: str) -> dict[str, Any]:
    state = load_ai_settings_state()
    found = None
    for item in state.get("providers") or []:
        item["is_default"] = str(item.get("id") or "") == str(provider_id or "").strip()
        if item["is_default"]:
            item["updated_at"] = _now_iso()
            found = item
    save_ai_settings_state(state)
    if not found:
        raise KeyError(provider_id)
    return _mask_provider(found)


def record_ai_provider_test_result(provider_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
    normalized_id = str(provider_id or "").strip()
    if not normalized_id:
        return None
    state = load_ai_settings_state()
    found = None
    for item in state.get("providers") or []:
        if str(item.get("id") or "").strip() != normalized_id:
            continue
        item["last_test_result"] = {
            "ok": bool(result.get("ok")),
            "message": str(result.get("message") or "").strip(),
            "tested_at": result.get("tested_at"),
            "model_count": result.get("model_count"),
            "api_root": result.get("api_root"),
        }
        item["updated_at"] = _now_iso()
        found = item
        break
    if not found:
        return None
    save_ai_settings_state(state)
    return _mask_provider(found)


def get_default_ai_provider(*, include_secret: bool = False) -> dict[str, Any] | None:
    state = load_ai_settings_state()
    providers = [dict(item) for item in state.get("providers") or []]
    provider = next((item for item in providers if item.get("is_default")), None)
    if not provider and providers:
        provider = providers[0]
    if not provider:
        return None
    return dict(provider) if include_secret else _mask_provider(provider)


def list_ai_knowledge_documents() -> dict[str, Any]:
    state = load_ai_settings_state()
    custom_docs = {str(item.get("id") or ""): dict(item) for item in state.get("documents") or []}
    documents: list[dict[str, Any]] = []
    for item in BUILTIN_DOCUMENTS:
        override = custom_docs.get(item["id"], {})
        content = item["path"].read_text(encoding="utf-8") if item["path"].exists() else ""
        documents.append(
            {
                "id": item["id"],
                "title": override.get("title") or item["title"],
                "description": override.get("description") or item["description"],
                "scope": _normalize_scope(override.get("scope") or item.get("scope")),
                "enabled": bool(override.get("enabled") if "enabled" in override else item.get("enabled", True)),
                "source_type": "builtin",
                "updated_at": override.get("updated_at") or (datetime.fromtimestamp(item["path"].stat().st_mtime, tz=UTC).isoformat() if item["path"].exists() else None),
                "content_preview": content[:500],
                "content_length": len(content),
            }
        )
    for item in state.get("documents") or []:
        if str(item.get("source_type") or "") == "builtin":
            continue
        content = str(item.get("content") or "")
        documents.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "description": item.get("description") or "",
                "scope": _normalize_scope(item.get("scope")),
                "enabled": bool(item.get("enabled", True)),
                "source_type": "custom",
                "updated_at": item.get("updated_at"),
                "content_preview": content[:500],
                "content_length": len(content),
            }
        )
    documents.sort(key=lambda row: (0 if row.get("source_type") == "builtin" else 1, row.get("title") or ""))
    return {"generated_at": _now_iso(), "documents": documents}


def get_ai_knowledge_document(doc_id: str) -> dict[str, Any] | None:
    normalized = str(doc_id or "").strip()
    state = load_ai_settings_state()
    for item in BUILTIN_DOCUMENTS:
        if item["id"] != normalized:
            continue
        override = next((row for row in state.get("documents") or [] if str(row.get("id") or "") == normalized), {})
        content = item["path"].read_text(encoding="utf-8") if item["path"].exists() else ""
        return {
            "id": normalized,
            "title": override.get("title") or item["title"],
            "description": override.get("description") or item["description"],
            "scope": _normalize_scope(override.get("scope") or item.get("scope")),
            "enabled": bool(override.get("enabled") if "enabled" in override else item.get("enabled", True)),
            "source_type": "builtin",
            "content": content,
            "updated_at": override.get("updated_at") or (datetime.fromtimestamp(item["path"].stat().st_mtime, tz=UTC).isoformat() if item["path"].exists() else None),
        }
    for item in state.get("documents") or []:
        if str(item.get("id") or "") == normalized:
            return dict(item)
    return None


def upsert_ai_knowledge_document(payload: dict[str, Any]) -> dict[str, Any]:
    normalized_id = str(payload.get("id") or "").strip()
    state = load_ai_settings_state()
    documents = [dict(item) for item in state.get("documents") or []]
    builtin = next((item for item in BUILTIN_DOCUMENTS if item["id"] == normalized_id), None)
    if builtin:
        existing = next((item for item in documents if str(item.get("id") or "") == normalized_id), None)
        override = {
            "id": normalized_id,
            "title": str(payload.get("title") or builtin["title"]).strip(),
            "description": str(payload.get("description") or builtin["description"]).strip(),
            "scope": _normalize_scope(payload.get("scope") if "scope" in payload else (existing or {}).get("scope") or builtin.get("scope")),
            "enabled": bool(payload.get("enabled") if "enabled" in payload else (existing or {}).get("enabled", True)),
            "source_type": "builtin",
            "updated_at": _now_iso(),
        }
        documents = [item for item in documents if str(item.get("id") or "") != normalized_id]
        documents.append(override)
        state["documents"] = documents
        save_ai_settings_state(state)
        return get_ai_knowledge_document(normalized_id) or override
    existing = next((item for item in documents if str(item.get("id") or "") == normalized_id), None)
    normalized = _normalize_custom_document(payload, existing)
    documents = [item for item in documents if str(item.get("id") or "") != normalized["id"]]
    documents.append(normalized)
    state["documents"] = documents
    save_ai_settings_state(state)
    return dict(normalized)


def delete_ai_knowledge_document(doc_id: str) -> dict[str, Any]:
    normalized = str(doc_id or "").strip()
    state = load_ai_settings_state()
    documents = [dict(item) for item in state.get("documents") or []]
    state["documents"] = [item for item in documents if str(item.get("id") or "") != normalized]
    save_ai_settings_state(state)
    return {"document_id": normalized, "deleted_at": _now_iso(), "removed": len(documents) != len(state["documents"])}


def get_ai_behavior_settings() -> dict[str, Any]:
    state = load_ai_settings_state()
    behavior = dict(DEFAULT_BEHAVIOR_SETTINGS)
    behavior.update(state.get("behavior") or {})
    if not behavior.get("updated_at"):
        behavior["updated_at"] = state.get("updated_at")
    return behavior


def update_ai_behavior_settings(payload: dict[str, Any]) -> dict[str, Any]:
    state = load_ai_settings_state()
    behavior = get_ai_behavior_settings()
    behavior.update(
        {
            "system_prompt": str(payload.get("system_prompt") or behavior.get("system_prompt") or "").strip(),
            "strict_document_mode": bool(payload.get("strict_document_mode") if "strict_document_mode" in payload else behavior.get("strict_document_mode", True)),
            "allow_freeform_suggestions": bool(payload.get("allow_freeform_suggestions") if "allow_freeform_suggestions" in payload else behavior.get("allow_freeform_suggestions", False)),
            "prefer_workflow_jump": bool(payload.get("prefer_workflow_jump") if "prefer_workflow_jump" in payload else behavior.get("prefer_workflow_jump", True)),
            "show_reasoning_summary": bool(payload.get("show_reasoning_summary") if "show_reasoning_summary" in payload else behavior.get("show_reasoning_summary", True)),
            "allow_auto_prefill": bool(payload.get("allow_auto_prefill") if "allow_auto_prefill" in payload else behavior.get("allow_auto_prefill", True)),
            "updated_at": _now_iso(),
        }
    )
    state["behavior"] = behavior
    save_ai_settings_state(state)
    return behavior
