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


def resolve_api_fallback_provider(*, workflow_scope: str | None = None, exclude_provider_id: str = "") -> dict[str, Any] | None:
    providers = [dict(item) for item in (load_ai_settings_state().get("providers") or []) if isinstance(item, dict)]
    normalized_exclude = str(exclude_provider_id or "").strip()
    candidates = []
    for item in providers:
        if not item.get("enabled"):
            continue
        if str(item.get("mode") or "").strip() != "api":
            continue
        if normalized_exclude and str(item.get("id") or "").strip() == normalized_exclude:
            continue
        if not _provider_matches_scope(item, workflow_scope):
            continue
        if not str(item.get("base_url") or "").strip():
            continue
        if not str(item.get("model_name") or "").strip():
            continue
        candidates.append(item)
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            1 if str(item.get("api_key") or "").strip() else 0,
            1 if item.get("is_default") else 0,
        ),
        reverse=True,
    )
    return candidates[0]


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


def _strip_v1_root(base_url: str, api_path: str) -> str:
    api_root = _compose_api_root(base_url, api_path).rstrip("/")
    if api_root.endswith("/v1"):
        return api_root[:-3].rstrip("/")
    return api_root


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
    model_name = str(config.get("model_name") or "").strip()
    model_ids = {
        str(item.get("id") or item.get("name") or "").strip()
        for item in (models if isinstance(models, list) else [])
        if isinstance(item, dict) and str(item.get("id") or item.get("name") or "").strip()
    }
    if model_name:
        if model_count <= 0:
            return {
                "ok": False,
                "message": f"服务在线，但当前没有暴露任何模型，无法使用 {model_name}。",
                "tested_at": tested_at,
                "model_count": model_count,
                "api_root": api_root,
            }
        if model_name not in model_ids:
            return {
                "ok": False,
                "message": f"服务在线，但模型 {model_name} 未加载到当前运行时。",
                "tested_at": tested_at,
                "model_count": model_count,
                "api_root": api_root,
            }
    return {
        "ok": True,
        "message": "连接成功，当前模型已可用于对话。" if model_name else "连接成功，可继续作为 AI provider 使用。",
        "tested_at": tested_at,
        "model_count": model_count,
        "api_root": api_root,
    }


def request_planner_completion(*, config: dict[str, Any], system_prompt: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    api_root = _compose_api_root(str(config.get("base_url") or ""), str(config.get("api_path") or "/v1"))
    model_name = str(config.get("model_name") or "").strip()
    if not api_root or not model_name:
        return None
    mode = str(config.get("mode") or "").strip()
    timeout = max(5, min(300, int(config.get("timeout") or 45)))
    max_tokens = int(config.get("max_tokens") or 900)
    if mode == "local":
        # Local runtimes on this machine can hang for several minutes on large models.
        # Keep the window short so the planner can fail over to a remote API promptly.
        timeout = max(45, min(timeout, 75))
        max_tokens = min(max_tokens, 96)
        compact_payload = {
            "goal": str(payload.get("goal") or "").strip(),
            "task_type": str(payload.get("task_type") or "").strip(),
            "workflow_scope": str(payload.get("workflow_scope") or "").strip(),
            "workflow_context": payload.get("workflow_context") if isinstance(payload.get("workflow_context"), dict) else {},
            "recent_user_message": "",
            "memory_hint": "",
            "response_style": "compact_json",
        }
        history_rows = payload.get("conversation_history") if isinstance(payload.get("conversation_history"), list) else []
        memory_rows = payload.get("memory_context") if isinstance(payload.get("memory_context"), list) else []
        recent_user = next(
            (str(item.get("text") or "").strip() for item in reversed(history_rows) if isinstance(item, dict) and str(item.get("role") or "").strip() == "user" and str(item.get("text") or "").strip()),
            "",
        )
        memory_hint = next(
            (
                str(item.get("summary") or item.get("title") or item.get("content") or "").strip()
                for item in memory_rows
                if isinstance(item, dict) and str(item.get("summary") or item.get("title") or item.get("content") or "").strip()
            ),
            "",
        )
        compact_payload["recent_user_message"] = recent_user[:240]
        compact_payload["memory_hint"] = memory_hint[:240]
        payload = compact_payload
    body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": float(config.get("temperature") or 0.2),
        "max_tokens": max(32, min(4096, max_tokens)),
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = _build_headers(config)
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        if mode == "local":
            ollama_root = _strip_v1_root(str(config.get("base_url") or ""), str(config.get("api_path") or "/v1"))
            prompt = (
                f"{system_prompt}\n\n"
                "只返回 JSON，对象只允许包含 summary、risks、suggested_path 三个字段。\n"
                "summary 要短，risks 是字符串数组，suggested_path 是简短路径提示。\n\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
            )
            generate_resp = client.post(
                f"{ollama_root}/api/generate",
                headers={"Content-Type": "application/json"},
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": body["temperature"],
                        "num_predict": body["max_tokens"],
                        "num_ctx": 1024,
                    },
                },
            )
            generate_resp.raise_for_status()
            data = generate_resp.json()
            content = data.get("response")
            if not content:
                return None
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = {"summary": str(content).strip()}
            return normalize_planner_response(parsed)
        try:
            resp = client.post(f"{api_root}/chat/completions", headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
        except httpx.HTTPStatusError as exc:
            if mode != "local" or exc.response.status_code != 404:
                raise
            ollama_root = _strip_v1_root(str(config.get("base_url") or ""), str(config.get("api_path") or "/v1"))
            try:
                ollama_resp = client.post(
                    f"{ollama_root}/api/chat",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": model_name,
                        "messages": body["messages"],
                        "stream": False,
                        "options": {
                            "temperature": body["temperature"],
                            "num_predict": body["max_tokens"],
                        },
                    },
                )
                ollama_resp.raise_for_status()
                data = ollama_resp.json()
                content = data.get("message", {}).get("content")
            except httpx.HTTPStatusError as ollama_exc:
                if ollama_exc.response.status_code != 404:
                    raise
                prompt = f"{system_prompt}\n\n请输出紧凑 JSON。\n\n用户请求:\n{json.dumps(payload, ensure_ascii=False)}"
                generate_resp = client.post(
                    f"{ollama_root}/api/generate",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {
                            "temperature": body["temperature"],
                            "num_predict": body["max_tokens"],
                        },
                    },
                )
                generate_resp.raise_for_status()
                data = generate_resp.json()
                content = data.get("response")
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
