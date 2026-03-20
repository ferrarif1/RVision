from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.db.models import DataAsset, ModelRecord
from app.security.dependencies import AuthUser
from app.security.roles import is_buyer_user
from app.services.ai_context_service import assemble_ai_context, normalize_workflow_scope
from app.services.ai_provider_service import request_planner_completion, resolve_provider_config, test_provider_connection
from app.services.assistant_paths import build_training_path, build_workflow_path
from app.services.model_router_service import TASK_TYPE_KEYWORDS, TASK_TYPE_LABELS, recommend_small_models

UTC = timezone.utc
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if not (PROJECT_ROOT / "config").exists() and Path("/app/config").exists():
    PROJECT_ROOT = Path("/app")
CONFIG_CANDIDATES = (
    PROJECT_ROOT / "config" / "assistant_local_llm_catalog.json",
    Path("/app/config/assistant_local_llm_catalog.json"),
)
PROVIDER_CANDIDATES = (
    PROJECT_ROOT / "config" / "assistant_provider_modes.json",
    Path("/app/config/assistant_provider_modes.json"),
)
RUNTIME_ROOT = PROJECT_ROOT / ".runtime" / "assistant_llm"
DOWNLOAD_ROOT = RUNTIME_ROOT / "downloads"
DOWNLOAD_JOB_ROOT = RUNTIME_ROOT / "jobs"
CATALOG_CACHE_PATH = RUNTIME_ROOT / "catalog_cache.json"
CATALOG_REFRESH_TTL = timedelta(hours=24)
DOWNLOAD_SCRIPT = PROJECT_ROOT / "docker" / "scripts" / "download_curated_llm_snapshot.py"
PROGRESS_RE = re.compile(r"(?P<pct>\d{1,3})%")

OCR_TASK_TYPES = {"car_number_ocr", "inspection_mark_ocr", "performance_mark_ocr"}
STATE_TASK_TYPES = {"door_lock_state_detect", "connector_defect_detect", "bolt_missing_detect"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_runtime_dirs() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_JOB_ROOT.mkdir(parents=True, exist_ok=True)


def _json_load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _find_existing_path(candidates: tuple[Path, ...]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _repo_target_dir(repo_id: str) -> Path:
    return DOWNLOAD_ROOT / str(repo_id or "").strip().replace("/", "__")


def _host_mark_path(source: str) -> Path:
    source_path = Path(str(source or ""))
    if str(source_path).startswith("/run/host_mark/"):
        return Path("/") / source_path.name
    return source_path


def _resolve_host_visible_path(target: Path) -> str:
    resolved = target.resolve()
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.exists():
        return str(resolved)
    best_match: tuple[int, Path, str, str] | None = None
    for raw_line in mountinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
        if " - " not in raw_line:
            continue
        left, right = raw_line.split(" - ", 1)
        left_parts = left.split()
        right_parts = right.split()
        if len(left_parts) < 5 or len(right_parts) < 2:
            continue
        mount_root = left_parts[3]
        mount_point = Path(left_parts[4])
        mount_source = right_parts[1]
        try:
            relative = resolved.relative_to(mount_point)
        except ValueError:
            continue
        score = len(str(mount_point))
        if best_match and score <= best_match[0]:
            continue
        best_match = (score, relative, mount_root, mount_source)
    if not best_match:
        return str(resolved)
    _, relative, mount_root, mount_source = best_match
    host_root = _host_mark_path(mount_source)
    if mount_root and mount_root != "/":
        host_root = host_root.joinpath(*Path(mount_root).parts[1:])
    return str((host_root / relative).resolve())


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _resolve_runtime_alias(model_row: dict[str, Any], runtime_status: dict[str, Any] | None = None) -> tuple[str | None, bool]:
    aliases = model_row.get("runtime_aliases") if isinstance(model_row.get("runtime_aliases"), dict) else {}
    alias = str(aliases.get("ollama") or aliases.get("local_openai_compatible") or "").strip()
    if not alias:
        return None, False
    runtime_payload = runtime_status if isinstance(runtime_status, dict) else {}
    runtime_models = runtime_payload.get("models") if isinstance(runtime_payload.get("models"), list) else []
    normalized_models = {str(item or "").strip() for item in runtime_models if str(item or "").strip()}
    return alias, alias in normalized_models


def _parse_log_progress(log_path: Path) -> int | None:
    if not log_path.exists():
        return None
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    matches = PROGRESS_RE.findall(text[-12000:])
    if not matches:
        return None
    try:
        return max(0, min(100, int(matches[-1])))
    except ValueError:
        return None


def _catalog_model_row(repo_id: str, *, force_refresh: bool = False) -> dict[str, Any]:
    normalized_repo_id = str(repo_id or "").strip()
    if not normalized_repo_id:
        return {}
    base_row = next(
        (item for item in (_local_catalog_base().get("models") or []) if str(item.get("repo_id") or "").strip() == normalized_repo_id),
        {},
    )
    catalog = get_local_llm_catalog(force_refresh=force_refresh)
    runtime_row = next(
        (item for item in (catalog.get("models") or []) if str(item.get("repo_id") or "").strip() == normalized_repo_id),
        {},
    )
    merged = dict(base_row or {})
    merged.update(runtime_row or {})
    return merged


def _resolve_download_strategy(repo_id: str) -> dict[str, Any]:
    model_row = _catalog_model_row(repo_id, force_refresh=False)
    runtime_status = get_local_llm_runtime_status()
    runtime_model_name, runtime_available = _resolve_runtime_alias(model_row, runtime_status)
    base_url = str(runtime_status.get("base_url") or runtime_status.get("recommended_base_url") or "").strip()
    strategy = "ollama" if runtime_status.get("ok") and runtime_model_name and base_url else "huggingface"
    return {
        "strategy": strategy,
        "runtime_model_name": runtime_model_name,
        "runtime_available": runtime_available,
        "base_url": base_url,
        "model_row": model_row,
    }


def _delete_runtime_model(*, base_url: str, runtime_model_name: str) -> dict[str, Any]:
    api_root = str(base_url or "").strip().rstrip("/")
    if api_root.endswith("/v1"):
        api_root = api_root[:-3].rstrip("/")
    model_name = str(runtime_model_name or "").strip()
    if not api_root or not model_name:
        return {"removed": False, "message": "missing runtime model config"}
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True, trust_env=False) as client:
            resp = client.request("DELETE", f"{api_root}/api/delete", json={"name": model_name}, headers={"Content-Type": "application/json"})
            if resp.status_code >= 400:
                try:
                    detail = resp.text
                except Exception:
                    detail = ""
                return {"removed": False, "message": detail or f"status={resp.status_code}"}
        return {"removed": True, "message": "runtime model removed"}
    except Exception as exc:
        return {"removed": False, "message": str(exc)}


def _hydrate_job_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    job = dict(payload)
    target_dir = Path(str(job.get("target_dir") or "")).expanduser()
    log_path = Path(str(job.get("log_file") or "")).expanduser()
    status = str(job.get("status") or "unknown").strip() or "unknown"
    strategy = str(job.get("strategy") or "huggingface").strip() or "huggingface"
    runtime_model_name = str(job.get("runtime_model_name") or "").strip()
    progress_pct = 0
    if status == "succeeded":
        progress_pct = 100
    elif status in {"starting", "running"}:
        progress_pct = int(job.get("progress_pct") or 0) if strategy == "ollama" else (_parse_log_progress(log_path) or 0)
    elif status == "failed":
        progress_pct = int(job.get("progress_pct") or 0) if strategy == "ollama" else (_parse_log_progress(log_path) or 0)
    runtime_ready = bool(job.get("runtime_ready"))
    if strategy == "ollama" and runtime_model_name:
        try:
            runtime_status = get_local_llm_runtime_status()
            runtime_models = runtime_status.get("models") if isinstance(runtime_status.get("models"), list) else []
            runtime_ready = runtime_model_name in {str(item or "").strip() for item in runtime_models if str(item or "").strip()}
        except Exception:
            runtime_ready = bool(job.get("runtime_ready"))
    job["progress_pct"] = progress_pct
    job["progress_label"] = (
        "已完成"
        if status == "succeeded"
        else "已取消"
        if status.startswith("cancel")
        else "下载失败"
        if status == "failed"
        else f"{progress_pct}%"
    )
    job["downloaded_bytes"] = int(job.get("downloaded_bytes") or 0) if strategy == "ollama" else _dir_size_bytes(target_dir)
    job["has_local_snapshot"] = target_dir.exists() and any(target_dir.iterdir()) if target_dir.exists() else False
    job["runtime_ready"] = runtime_ready
    return job


@lru_cache(maxsize=1)
def _local_catalog_base() -> dict[str, Any]:
    path = _find_existing_path(CONFIG_CANDIDATES)
    payload = _json_load(path)
    models = payload.get("models") if isinstance(payload.get("models"), list) else []
    payload["models"] = [item for item in models if isinstance(item, dict)]
    return payload


@lru_cache(maxsize=1)
def _provider_modes_payload() -> dict[str, Any]:
    path = _find_existing_path(PROVIDER_CANDIDATES)
    payload = _json_load(path)
    modes = payload.get("modes") if isinstance(payload.get("modes"), list) else []
    payload["modes"] = [item for item in modes if isinstance(item, dict)]
    return payload


def _catalog_cache_is_fresh(payload: dict[str, Any]) -> bool:
    refreshed_at = str(payload.get("refreshed_at") or "").strip()
    if not refreshed_at:
        return False
    try:
        ts = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return ts >= datetime.now(UTC) - CATALOG_REFRESH_TTL


def _fetch_hf_model_metadata(repo_id: str) -> dict[str, Any]:
    url = f"https://huggingface.co/api/models/{repo_id}"
    with httpx.Client(timeout=20.0, follow_redirects=True, trust_env=False) as client:
        resp = client.get(url)
        resp.raise_for_status()
        payload = resp.json()
    siblings = payload.get("siblings") if isinstance(payload.get("siblings"), list) else []
    return {
        "downloads": int(payload.get("downloads") or 0),
        "likes": int(payload.get("likes") or 0),
        "last_modified": payload.get("lastModified"),
        "pipeline_tag": payload.get("pipeline_tag"),
        "gated": bool(payload.get("gated") or False),
        "private": bool(payload.get("private") or False),
        "siblings_count": len(siblings),
        "sha": payload.get("sha"),
        "tags": [str(item) for item in payload.get("tags") or [] if str(item).strip()][:20],
    }


def refresh_local_llm_catalog_cache() -> dict[str, Any]:
    _ensure_runtime_dirs()
    base = _local_catalog_base()
    refreshed_models: list[dict[str, Any]] = []
    for item in base.get("models") or []:
        repo_id = str(item.get("repo_id") or "").strip()
        merged = dict(item)
        try:
            merged["runtime_metadata"] = _fetch_hf_model_metadata(repo_id)
            merged["metadata_status"] = "ok"
        except Exception as exc:  # pragma: no cover - external network tolerance
            merged["runtime_metadata"] = {}
            merged["metadata_status"] = "stale"
            merged["metadata_error"] = str(exc)
        refreshed_models.append(merged)
    payload = {
        "refreshed_at": _now_iso(),
        "ranking_policy": base.get("ranking_policy"),
        "last_updated": base.get("last_updated"),
        "models": refreshed_models,
    }
    CATALOG_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def get_local_llm_catalog(*, force_refresh: bool = False) -> dict[str, Any]:
    _ensure_runtime_dirs()
    runtime_status = get_local_llm_runtime_status()
    base_models = {
        str(item.get("repo_id") or "").strip(): dict(item)
        for item in (_local_catalog_base().get("models") or [])
        if isinstance(item, dict) and str(item.get("repo_id") or "").strip()
    }
    if not force_refresh and CATALOG_CACHE_PATH.exists():
        payload = _json_load(CATALOG_CACHE_PATH)
        base_repo_ids = {
            str(item.get("repo_id") or "").strip()
            for item in (_local_catalog_base().get("models") or [])
            if str(item.get("repo_id") or "").strip()
        }
        cached_repo_ids = {
            str(item.get("repo_id") or "").strip()
            for item in (payload.get("models") or [])
            if isinstance(item, dict) and str(item.get("repo_id") or "").strip()
        }
        if _catalog_cache_is_fresh(payload) and base_repo_ids.issubset(cached_repo_ids):
            models = []
            for item in payload.get("models") or []:
                if not isinstance(item, dict):
                    continue
                repo_id = str(item.get("repo_id") or "").strip()
                merged = dict(base_models.get(repo_id) or {})
                merged.update(dict(item))
                models.append(merged)
            for item in models:
                target_dir = _repo_target_dir(str(item.get("repo_id") or ""))
                installed = target_dir.exists() and any(target_dir.iterdir()) if target_dir.exists() else False
                runtime_model_name, runtime_available = _resolve_runtime_alias(item, runtime_status)
                item["installed"] = installed
                item["local_path"] = str(target_dir)
                item["local_size_bytes"] = _dir_size_bytes(target_dir) if installed else 0
                item["runtime_model_name"] = runtime_model_name
                item["runtime_available"] = runtime_available
            payload["models"] = models
            return payload
    payload = refresh_local_llm_catalog_cache()
    models = [dict(item) for item in payload.get("models") or []]
    for item in models:
        target_dir = _repo_target_dir(str(item.get("repo_id") or ""))
        installed = target_dir.exists() and any(target_dir.iterdir()) if target_dir.exists() else False
        runtime_model_name, runtime_available = _resolve_runtime_alias(item, runtime_status)
        item["installed"] = installed
        item["local_path"] = str(target_dir)
        item["local_size_bytes"] = _dir_size_bytes(target_dir) if installed else 0
        item["runtime_model_name"] = runtime_model_name
        item["runtime_available"] = runtime_available
    payload["models"] = models
    return payload


def get_provider_modes() -> dict[str, Any]:
    payload = dict(_provider_modes_payload())
    payload["generated_at"] = _now_iso()
    return payload


def _job_path(job_id: str) -> Path:
    return DOWNLOAD_JOB_ROOT / f"{job_id}.json"


def _read_job(path: Path) -> dict[str, Any]:
    try:
        payload = _json_load(path)
    except Exception:
        payload = {}
    payload["job_id"] = path.stem
    return _hydrate_job_runtime(payload)


def list_local_llm_download_jobs() -> list[dict[str, Any]]:
    _ensure_runtime_dirs()
    rows = [_read_job(path) for path in sorted(DOWNLOAD_JOB_ROOT.glob("*.json"), reverse=True)]
    rows.sort(key=lambda item: str(item.get("created_at") or item.get("started_at") or ""), reverse=True)
    return rows


def start_local_llm_download(*, repo_id: str, display_name: str | None = None) -> dict[str, Any]:
    _ensure_runtime_dirs()
    job_id = f"llm-dl-{uuid.uuid4().hex[:12]}"
    target_dir = _repo_target_dir(repo_id)
    status_path = _job_path(job_id)
    log_path = DOWNLOAD_JOB_ROOT / f"{job_id}.log"
    strategy = _resolve_download_strategy(repo_id)
    cmd = [
        sys.executable,
        str(DOWNLOAD_SCRIPT),
        "--repo-id",
        repo_id,
        "--target-dir",
        str(target_dir),
        "--status-file",
        str(status_path),
        "--log-file",
        str(log_path),
        "--strategy",
        str(strategy.get("strategy") or "huggingface"),
    ]
    if strategy.get("strategy") == "ollama":
        cmd.extend(["--base-url", str(strategy.get("base_url") or ""), "--runtime-model", str(strategy.get("runtime_model_name") or "")])
    env = os.environ.copy()
    log_handle = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT, env=env)
    bootstrap_payload = {
        "job_id": job_id,
        "repo_id": repo_id,
        "display_name": display_name or str(strategy.get("model_row", {}).get("display_name") or repo_id),
        "status": "starting",
        "created_at": _now_iso(),
        "pid": proc.pid,
        "target_dir": str(target_dir),
        "status_file": str(status_path),
        "log_file": str(log_path),
        "strategy": str(strategy.get("strategy") or "huggingface"),
        "runtime_model_name": str(strategy.get("runtime_model_name") or ""),
        "base_url": str(strategy.get("base_url") or ""),
        "runtime_ready": bool(strategy.get("runtime_available")),
    }
    status_path.write_text(json.dumps(bootstrap_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return _hydrate_job_runtime(bootstrap_payload)


def cancel_local_llm_download(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    payload = _read_job(path)
    pid = int(payload.get("pid") or 0)
    if pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
            payload["status"] = "cancelled"
        except ProcessLookupError:
            payload["status"] = "cancelled"
    payload["cancelled_at"] = _now_iso()
    _remove_path(Path(str(payload.get("target_dir") or "")).expanduser())
    _remove_path(Path(str(payload.get("log_file") or "")).expanduser())
    _remove_path(path)
    payload["record_removed"] = True
    return _hydrate_job_runtime(payload)


def delete_local_llm(repo_id: str) -> dict[str, Any]:
    normalized_repo_id = str(repo_id or "").strip()
    target_dir = _repo_target_dir(normalized_repo_id)
    removed_local_snapshot = target_dir.exists()
    _remove_path(target_dir)
    model_row = _catalog_model_row(normalized_repo_id, force_refresh=False)
    runtime_status = get_local_llm_runtime_status()
    runtime_model_name, runtime_available = _resolve_runtime_alias(model_row, runtime_status)
    runtime_delete_result = {"removed": False, "message": "", "runtime_model_name": runtime_model_name}
    if runtime_available and runtime_model_name and runtime_status.get("ok"):
        runtime_delete_result = _delete_runtime_model(
            base_url=str(runtime_status.get("base_url") or runtime_status.get("recommended_base_url") or ""),
            runtime_model_name=runtime_model_name,
        ) | {"runtime_model_name": runtime_model_name}
    removed_job_records = 0
    for job_path in DOWNLOAD_JOB_ROOT.glob("*.json"):
        job = _read_job(job_path)
        if str(job.get("repo_id") or "").strip() != normalized_repo_id:
            continue
        pid = int(job.get("pid") or 0)
        if pid > 0 and str(job.get("status") or "") in {"starting", "running"}:
            continue
        _remove_path(Path(str(job.get("log_file") or "")).expanduser())
        _remove_path(job_path)
        removed_job_records += 1
    removed_provider_ids: list[str] = []
    from app.services.ai_settings_service import delete_ai_provider_config, load_ai_settings_state

    for provider in load_ai_settings_state().get("providers") or []:
        if str(provider.get("mode") or "") != "local":
            continue
        provider_model_name = str(provider.get("model_name") or "").strip()
        if provider_model_name not in {normalized_repo_id, str(runtime_model_name or "").strip()}:
            continue
        provider_id = str(provider.get("id") or "").strip()
        if not provider_id:
            continue
        try:
            delete_ai_provider_config(provider_id)
            removed_provider_ids.append(provider_id)
        except Exception:
            continue
    return {
        "repo_id": normalized_repo_id,
        "target_dir": str(target_dir),
        "removed_local_snapshot": removed_local_snapshot,
        "removed_runtime_model": bool(runtime_delete_result.get("removed")),
        "runtime_model_name": runtime_delete_result.get("runtime_model_name"),
        "runtime_delete_message": str(runtime_delete_result.get("message") or "").strip(),
        "removed_job_records": removed_job_records,
        "removed_provider_ids": removed_provider_ids,
        "deleted_at": _now_iso(),
    }


def get_local_llm_folder_info(repo_id: str) -> dict[str, Any]:
    normalized_repo_id = str(repo_id or "").strip()
    target_dir = _repo_target_dir(normalized_repo_id)
    host_path = _resolve_host_visible_path(target_dir)
    return {
        "repo_id": normalized_repo_id,
        "target_dir": str(target_dir),
        "host_path": host_path,
        "exists": target_dir.exists(),
        "open_command": f'open "{host_path}"',
        "generated_at": _now_iso(),
    }


def get_local_llm_runtime_status() -> dict[str, Any]:
    from app.services.ai_settings_service import _default_local_base_url, get_default_ai_provider

    default_provider = get_default_ai_provider(include_secret=True) or {}
    candidate = dict(default_provider) if str(default_provider.get("mode") or "") == "local" else {}
    base_url = str(candidate.get("base_url") or _default_local_base_url()).strip()
    api_path = str(candidate.get("api_path") or "/v1").strip() or "/v1"
    config = {
        "provider": "local_openai_compatible",
        "mode": "local",
        "base_url": base_url,
        "api_path": api_path,
        "api_key": str(candidate.get("api_key") or "").strip(),
        "organization": str(candidate.get("organization") or "").strip(),
        "project": str(candidate.get("project") or "").strip(),
        "timeout": int(candidate.get("timeout") or 10),
    }
    try:
        api_root = base_url.rstrip("/")
        if api_path and not api_root.endswith(api_path.rstrip("/")):
            api_root = f"{api_root}/{api_path.lstrip('/')}"
        models_url = f"{api_root}/models"
        with httpx.Client(timeout=5.0, follow_redirects=True, trust_env=False) as client:
            resp = client.get(models_url, headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            payload = resp.json()
        rows = payload.get("data") if isinstance(payload, dict) else []
        models = []
        if isinstance(rows, list):
            for item in rows[:24]:
                if isinstance(item, dict):
                    models.append(str(item.get("id") or item.get("name") or "").strip())
        return {
            "ok": True,
            "base_url": base_url,
            "api_path": api_path,
            "api_root": api_root,
            "recommended_base_url": base_url,
            "models": [item for item in models if item],
            "model_count": len([item for item in models if item]),
            "message": "本地兼容服务已在线。",
            "checked_at": _now_iso(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "base_url": base_url,
            "api_path": api_path,
            "recommended_base_url": base_url,
            "models": [],
            "model_count": 0,
            "message": f"本地兼容服务未连通：{exc}",
            "checked_at": _now_iso(),
        }


def activate_local_llm(repo_id: str) -> dict[str, Any]:
    normalized_repo_id = str(repo_id or "").strip()
    if not normalized_repo_id:
        raise ValueError("repo_id is required")
    target_dir = _repo_target_dir(normalized_repo_id)
    catalog = get_local_llm_catalog(force_refresh=False)
    model_row = next((item for item in catalog.get("models") or [] if str(item.get("repo_id") or "").strip() == normalized_repo_id), {})
    runtime_status = get_local_llm_runtime_status()
    runtime_model_name, runtime_available = _resolve_runtime_alias(model_row, runtime_status)
    has_snapshot = target_dir.exists() and any(target_dir.iterdir()) if target_dir.exists() else False
    if not has_snapshot and not runtime_available:
        raise FileNotFoundError(normalized_repo_id)
    from app.services.ai_settings_service import upsert_local_llm_provider

    provider = upsert_local_llm_provider(
        repo_id=normalized_repo_id,
        display_name=str(model_row.get("display_name") or normalized_repo_id),
        model_name=runtime_model_name or normalized_repo_id,
    )
    try:
        connection = test_provider_connection(provider)
    except Exception as exc:
        connection = {
            "ok": False,
            "message": f"本地兼容服务暂时不可用：{exc}",
            "tested_at": _now_iso(),
        }
    return {
        "repo_id": normalized_repo_id,
        "display_name": str(model_row.get("display_name") or normalized_repo_id),
        "provider_id": provider.get("id"),
        "provider_name": provider.get("name"),
        "model_name": provider.get("model_name"),
        "base_url": provider.get("base_url"),
        "api_path": provider.get("api_path"),
        "target_dir": str(target_dir),
        "host_path": _resolve_host_visible_path(target_dir),
        "has_snapshot": has_snapshot,
        "runtime_model_name": runtime_model_name,
        "runtime_available": runtime_available,
        "connection_ok": bool(connection.get("ok")),
        "connection_message": str(connection.get("message") or "").strip(),
        "activated_at": _now_iso(),
    }


def _infer_task_type_from_goal(goal: str) -> tuple[str | None, list[str]]:
    text = str(goal or "").strip().lower()
    if not text:
        return None, ["缺少目标描述，暂时只能给出通用建议。"]
    best_task = None
    best_score = 0
    matched_terms: list[str] = []
    for task_type, keywords in TASK_TYPE_KEYWORDS.items():
        score = 0
        local_terms: list[str] = []
        for keyword in keywords:
            if keyword and keyword in text:
                score += 1
                local_terms.append(keyword)
        if score > best_score:
            best_task = task_type
            best_score = score
            matched_terms = local_terms
    if best_task:
        return best_task, [f"命中目标词：{', '.join(dict.fromkeys(matched_terms)[:5])}"]
    return None, ["未命中稳定任务词，将保守给出通用下一步。"]


def _task_label(task_type: str | None) -> str:
    if not task_type:
        return "通用视觉任务"
    return TASK_TYPE_LABELS.get(task_type, task_type)


def _serialize_action(*, action_id: str, title: str, summary: str, path: str, reason: str, kind: str = "navigate", prefill: dict[str, Any] | None = None, priority: str = "secondary") -> dict[str, Any]:
    workflow_path = build_workflow_path(action_id, path)
    return {
        "action_id": action_id,
        "title": title,
        "summary": summary,
        "path": path,
        "expert_path": path,
        "workflow_path": workflow_path,
        "reason": reason,
        "kind": kind,
        "prefill": prefill or {},
        "priority": priority,
    }


def _latest_model_for_task(db: Session, task_type: str, *, status: str) -> ModelRecord | None:
    rows = (
        db.query(ModelRecord)
        .filter(ModelRecord.status == status)
        .order_by(ModelRecord.created_at.desc())
        .all()
    )
    for row in rows:
        manifest = row.manifest if isinstance(row.manifest, dict) else {}
        if str(manifest.get("task_type") or "").strip() == task_type:
            return row
    return None


def build_assistant_plan(
    db: Session,
    current_user: AuthUser,
    *,
    goal: str,
    asset_ids: list[str],
    current_task_type: str | None,
    current_model_id: str | None,
    llm_mode: str,
    llm_selection: dict[str, Any] | None,
    api_config: dict[str, Any] | None,
    workflow_context: dict[str, Any] | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    memory_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task_type = current_task_type
    signals: list[str] = []
    asset_rows: list[DataAsset] = []
    if asset_ids:
        asset_rows = db.query(DataAsset).filter(DataAsset.id.in_(tuple(asset_ids))).order_by(DataAsset.created_at.desc()).all()
    if not task_type:
        inferred, infer_signals = _infer_task_type_from_goal(goal)
        task_type = inferred
        signals.extend(infer_signals)
    selected_model = None
    recommendation = None
    if asset_rows and not current_model_id:
        try:
            recommendation = recommend_small_models(
                db,
                current_user,
                asset=asset_rows[0],
                device_code=None,
                requested_task_type=task_type,
                intent_text=goal,
                limit=3,
            ).to_dict()
            selected_model = recommendation.get("selected_model")
            if recommendation.get("summary"):
                signals.append(recommendation["summary"])
        except Exception:
            recommendation = None
    if current_model_id:
        row = db.query(ModelRecord).filter(ModelRecord.id == current_model_id).first()
        if row:
            selected_model = {
                "model_id": row.id,
                "model_code": row.model_code,
                "version": row.version,
                "task_type": str((row.manifest or {}).get("task_type") or task_type or "").strip(),
            }
            task_type = selected_model.get("task_type") or task_type

    released = _latest_model_for_task(db, task_type or "", status="RELEASED") if task_type else None
    submitted = _latest_model_for_task(db, task_type or "", status="SUBMITTED") if task_type else None
    approved = _latest_model_for_task(db, task_type or "", status="APPROVED") if task_type else None

    primary_action = None
    secondary_actions: list[dict[str, Any]] = []
    if selected_model or released:
        chosen = selected_model or {
            "model_id": released.id,
            "model_code": released.model_code,
            "version": released.version,
            "task_type": task_type,
        }
        primary_action = _serialize_action(
            action_id="validate_existing_model",
            title="先验证现有模型",
            summary="直接把目标、资产和模型带到任务中心，先跑一轮在线验证。",
            path="tasks",
            reason="当前已经存在一版可直接尝试的模型，先验证能最快得到反馈。",
            prefill={
                "taskModelId": chosen.get("model_id"),
                "taskType": chosen.get("task_type") or task_type,
                "taskAssetId": asset_rows[0].id if asset_rows else "",
                "taskHint": goal,
            },
            priority="primary",
        )
    elif task_type:
        primary_action = _serialize_action(
            action_id="prepare_training_data",
            title="先准备这类任务的数据",
            summary="当前没有现成模型可直接验证，优先进入对应的数据准备 / 复核工作区。",
            path=build_training_path(task_type),
            reason="你描述的目标已经清楚，但还缺可直接验证的现有模型。",
            prefill={"taskType": task_type},
            priority="primary",
        )
    else:
        primary_action = _serialize_action(
            action_id="upload_or_select_assets",
            title="先补输入信息",
            summary="系统还不能稳定判断你的目标，先上传图片或明确说明要识别什么。",
            path="assets" if not asset_rows else "tasks",
            reason="缺少稳定目标或可用资产，没法直接规划更靠后的动作。",
            priority="primary",
        )

    if task_type:
        secondary_actions.append(
            _serialize_action(
                action_id="open_training_path",
                title="查看训练与微调入口",
                summary=f"进入 {_task_label(task_type)} 的数据准备 / 训练入口。",
                path=build_training_path(task_type),
                reason="如果现有模型效果不够，可以立即转去数据准备和训练闭环。",
                prefill={"taskType": task_type},
            )
        )
    if submitted:
        secondary_actions.append(
            _serialize_action(
                action_id="open_approval_workbench",
                title="查看待验证模型审批",
                summary="当前已有待验证模型，可直接去模型中心审批工作台继续。",
                path="models",
                reason="该任务已经存在待验证模型，适合先做审批验证。",
                prefill={"focusModelId": submitted.id},
            )
        )
    if approved:
        secondary_actions.append(
            _serialize_action(
                action_id="open_release_workbench",
                title="查看发布准备",
                summary="当前已有已审批未发布模型，可直接进入发布工作台。",
                path="models",
                reason="这类任务已经到发布前阶段，适合继续配置设备与交付范围。",
                prefill={"focusModelId": approved.id},
            )
        )

    workflow_scope = normalize_workflow_scope(primary_action.get("workflow_path") if primary_action else "", primary_action.get("action_id") if primary_action else "")
    effective_provider = resolve_provider_config(
        llm_mode=llm_mode,
        llm_selection=llm_selection,
        api_config=api_config,
        workflow_scope=workflow_scope,
    )
    is_local_provider = bool(effective_provider and str(effective_provider.get("mode") or "").strip() == "local")
    ai_context = assemble_ai_context(workflow_scope=workflow_scope, task_type=task_type, goal=goal, compact=is_local_provider)
    workflow_context = workflow_context if isinstance(workflow_context, dict) else {}
    safe_history = conversation_history if isinstance(conversation_history, list) else []
    safe_memory = memory_context if isinstance(memory_context, list) else []
    history_limit = 2 if is_local_provider else 8
    memory_limit = 2 if is_local_provider else 8
    compact_history = [
        {
            "role": str(row.get("role") or "").strip(),
            "text": str(row.get("text") or "").strip(),
            "attachments": row.get("attachments") if isinstance(row.get("attachments"), list) else [],
        }
        for row in safe_history[:history_limit]
        if isinstance(row, dict) and (str(row.get("text") or "").strip() or isinstance(row.get("attachments"), list))
    ]
    compact_memory = [
        {
            "title": str(row.get("title") or "").strip(),
            "summary": str(row.get("summary") or "").strip(),
            "content": str(row.get("content") or "").strip(),
            "task_type": str(row.get("task_type") or "").strip(),
            "model_name": str(row.get("model_name") or "").strip(),
        }
        for row in safe_memory[:memory_limit]
        if isinstance(row, dict) and (
            str(row.get("title") or "").strip()
            or str(row.get("summary") or "").strip()
            or str(row.get("content") or "").strip()
        )
    ]

    llm_advice = None
    if effective_provider and llm_mode in {"api", "local"}:
        try:
            llm_advice = request_planner_completion(
                config=effective_provider,
                system_prompt=str(ai_context.get("system_prompt") or "").strip(),
                payload={
                    "goal": goal,
                    "task_type": task_type,
                    "task_label": _task_label(task_type),
                    "asset_file_names": [row.file_name for row in asset_rows][:2] if not is_local_provider else [],
                    "released_model": released.model_code if released else None,
                    "submitted_model": submitted.model_code if submitted else None,
                    "approved_model": approved.model_code if approved else None,
                    "selected_llm": {} if is_local_provider else (llm_selection or {}),
                    "workflow_scope": workflow_scope,
                    "workflow_context": workflow_context,
                    "conversation_history": compact_history,
                    "memory_context": compact_memory,
                    "response_style": "compact_json" if is_local_provider else "full_json",
                },
            )
        except Exception as exc:  # pragma: no cover - external runtime
            llm_advice = {
                "summary": "外部 API 大模型暂时没有返回稳定建议，当前已回退到平台内规划引擎。",
                "risks": [str(exc)],
            }

    return {
        "generated_at": _now_iso(),
        "goal": goal,
        "inferred_task_type": task_type,
        "inferred_task_label": _task_label(task_type),
        "llm_mode": llm_mode,
        "llm_selection": llm_selection or {},
        "provider_used": {
            "provider_id": str(effective_provider.get("id") or "").strip(),
            "name": str(effective_provider.get("name") or "").strip(),
            "mode": str(effective_provider.get("mode") or llm_mode).strip(),
            "model_name": str(effective_provider.get("model_name") or "").strip(),
        } if effective_provider else None,
        "signals": signals,
        "context_documents": [
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "scope": row.get("scope") or [],
                "source_type": row.get("source_type"),
                "updated_at": row.get("updated_at"),
            }
            for row in ai_context.get("documents") or []
        ],
        "behavior_settings": ai_context.get("behavior") or {},
        "workflow_context_input": workflow_context,
        "conversation_history_count": len(compact_history),
        "memory_context_count": len(compact_memory),
        "asset_summary": [
            {
                "asset_id": row.id,
                "file_name": row.file_name,
                "purpose": row.asset_purpose,
                "asset_type": row.asset_type,
            }
            for row in asset_rows[:5]
        ],
        "recommendation": recommendation,
        "current_state": {
            "released_model": {
                "model_id": released.id,
                "model_code": released.model_code,
                "version": released.version,
            } if released else None,
            "submitted_model": {
                "model_id": submitted.id,
                "model_code": submitted.model_code,
                "version": submitted.version,
            } if submitted else None,
            "approved_model": {
                "model_id": approved.id,
                "model_code": approved.model_code,
                "version": approved.version,
            } if approved else None,
        },
        "primary_action": primary_action,
        "secondary_actions": secondary_actions,
        "llm_advice": llm_advice,
        "guidance_summary": primary_action["summary"] if primary_action else "先补齐目标和资产，再继续下一步。",
    }
