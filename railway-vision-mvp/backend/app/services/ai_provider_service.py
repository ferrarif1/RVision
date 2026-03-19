from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

import httpx

from app.services.ai_settings_service import get_ai_provider_config, get_default_ai_provider, load_ai_settings_state


def _provider_matches_scope(config: dict[str, Any], workflow_scope: str | None) -> bool:
    scope = str(workflow_scope or "").strip() or "global"
    rows = [str(item or "").strip() for item in (config.get("scope") or []) if str(item or "").strip()]
    if not rows or "global" in rows:
        return True
    return scope in rows


def _scoped_saved_provider(*, llm_mode: str, workflow_scope: str | None) -> dict[str, Any] | None:
    scope = str(workflow_scope or "").strip() or "global"
    providers = [dict(item) for item in (load_ai_settings_state().get("providers") or []) if isinstance(item, dict)]
    providers = [item for item in providers if item.get("enabled")]
    providers = [item for item in providers if str(item.get("mode") or "") == llm_mode]
    exact = []
    fallback = []
    for item in providers:
        rows = [str(part or "").strip() for part in (item.get("scope") or []) if str(part or "").strip()]
        if scope != "global" and rows and "global" not in rows and scope in rows:
            exact.append(item)
        elif _provider_matches_scope(item, workflow_scope):
            fallback.append(item)
    preferred = exact or fallback or providers
    if not preferred:
        return None
    return next((item for item in preferred if item.get("is_default")), None) or preferred[0]


def resolve_provider_config(*, llm_mode: str, llm_selection: dict[str, Any] | None = None, api_config: dict[str, Any] | None = None, workflow_scope: str | None = None) -> dict[str, Any] | None:
    selection = llm_selection or {}
    provider_id = str(selection.get("provider_id") or (api_config or {}).get("provider_id") or "").strip()
    if provider_id:
        saved = get_ai_provider_config(provider_id, include_secret=True)
        if saved:
            merged = dict(saved)
            if api_config:
                for key, value in api_config.items():
                    if value not in (None, ""):
                        merged[key] = value
            return merged
    if llm_mode in {"api", "local"} and api_config:
        merged = dict(api_config)
        merged.setdefault("mode", llm_mode)
        return merged
    if llm_mode in {"api", "local"}:
        scoped_provider = _scoped_saved_provider(llm_mode=llm_mode, workflow_scope=workflow_scope)
        if scoped_provider:
            return scoped_provider
        default_provider = get_default_ai_provider(include_secret=True)
        if default_provider and str(default_provider.get("mode") or "") == llm_mode:
            return default_provider
    return None


def _compose_api_root(base_url: str, api_path: str) -> str:
    clean_base = str(base_url or "").strip().rstrip("/")
    clean_path = str(api_path or "").strip()
    if not clean_base:
        return ""
    if not clean_path:
        return clean_base
    if clean_base.endswith(clean_path.rstrip("/")):
        return clean_base
    return f"{clean_base}/{clean_path.lstrip('/')}"


def _build_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = str(config.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    organization = str(config.get("organization") or "").strip()
    project = str(config.get("project") or "").strip()
    if organization:
        headers["OpenAI-Organization"] = organization
    if project:
        headers["OpenAI-Project"] = project
    return headers


def test_provider_connection(config: dict[str, Any]) -> dict[str, Any]:
    api_root = _compose_api_root(str(config.get("base_url") or ""), str(config.get("api_path") or "/v1"))
    tested_at = datetime.now(timezone.utc).isoformat()
    if not api_root:
        return {
            "ok": False,
            "message": "缺少 Base URL，暂时无法测试连接。",
            "tested_at": tested_at,
        }
    timeout = max(5, min(300, int(config.get("timeout") or 45)))
    headers = _build_headers(config)
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        resp = client.get(f"{api_root}/models", headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    models = payload.get("data") if isinstance(payload, dict) else []
    model_count = len(models) if isinstance(models, list) else 0
    return {
        "ok": True,
        "message": "连接成功，可继续作为 AI provider 使用。",
        "tested_at": tested_at,
        "model_count": model_count,
        "api_root": api_root,
    }


def request_planner_completion(*, config: dict[str, Any], system_prompt: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    api_root = _compose_api_root(str(config.get("base_url") or ""), str(config.get("api_path") or "/v1"))
    model_name = str(config.get("model_name") or "").strip()
    if not api_root or not model_name:
        return None
    body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": float(config.get("temperature") or 0.2),
        "max_tokens": int(config.get("max_tokens") or 900),
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = _build_headers(config)
    timeout = max(5, min(300, int(config.get("timeout") or 45)))
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        resp = client.post(f"{api_root}/chat/completions", headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {"summary": str(content).strip()}
    return normalize_planner_response(parsed)


def normalize_planner_response(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload or not isinstance(payload, dict):
        return None
    risks = payload.get("risks") if isinstance(payload.get("risks"), list) else []
    return {
        "summary": str(payload.get("summary") or "").strip(),
        "risks": [str(item).strip() for item in risks if str(item).strip()][:3],
        "suggested_path": str(payload.get("suggested_path") or "").strip(),
    }
