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
from app.services.model_router_service import TASK_TYPE_KEYWORDS, TASK_TYPE_LABELS, recommend_small_models

UTC = timezone.utc
PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _find_existing_path(candidates: tuple[Path, ...]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _repo_target_dir(repo_id: str) -> Path:
    return DOWNLOAD_ROOT / str(repo_id or "").strip().replace("/", "__")


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


def _hydrate_job_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    job = dict(payload)
    target_dir = Path(str(job.get("target_dir") or "")).expanduser()
    log_path = Path(str(job.get("log_file") or "")).expanduser()
    status = str(job.get("status") or "unknown").strip() or "unknown"
    progress_pct = 0
    if status == "succeeded":
        progress_pct = 100
    elif status in {"starting", "running"}:
        progress_pct = _parse_log_progress(log_path) or 0
    elif status == "failed":
        progress_pct = _parse_log_progress(log_path) or 0
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
    job["downloaded_bytes"] = _dir_size_bytes(target_dir)
    job["has_local_snapshot"] = target_dir.exists() and any(target_dir.iterdir()) if target_dir.exists() else False
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
    if not force_refresh and CATALOG_CACHE_PATH.exists():
        payload = _json_load(CATALOG_CACHE_PATH)
        if _catalog_cache_is_fresh(payload):
            models = [dict(item) for item in payload.get("models") or []]
            for item in models:
                target_dir = _repo_target_dir(str(item.get("repo_id") or ""))
                installed = target_dir.exists() and any(target_dir.iterdir()) if target_dir.exists() else False
                item["installed"] = installed
                item["local_path"] = str(target_dir)
                item["local_size_bytes"] = _dir_size_bytes(target_dir) if installed else 0
            payload["models"] = models
            return payload
    payload = refresh_local_llm_catalog_cache()
    models = [dict(item) for item in payload.get("models") or []]
    for item in models:
        target_dir = _repo_target_dir(str(item.get("repo_id") or ""))
        installed = target_dir.exists() and any(target_dir.iterdir()) if target_dir.exists() else False
        item["installed"] = installed
        item["local_path"] = str(target_dir)
        item["local_size_bytes"] = _dir_size_bytes(target_dir) if installed else 0
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
    ]
    env = os.environ.copy()
    log_handle = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT, env=env)
    bootstrap_payload = {
        "job_id": job_id,
        "repo_id": repo_id,
        "display_name": display_name or repo_id,
        "status": "starting",
        "created_at": _now_iso(),
        "pid": proc.pid,
        "target_dir": str(target_dir),
        "status_file": str(status_path),
        "log_file": str(log_path),
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
    return {
        "repo_id": normalized_repo_id,
        "target_dir": str(target_dir),
        "removed_local_snapshot": removed_local_snapshot,
        "removed_job_records": removed_job_records,
        "deleted_at": _now_iso(),
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
    return {
        "action_id": action_id,
        "title": title,
        "summary": summary,
        "path": path,
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


def _build_training_path(task_type: str | None) -> str:
    if task_type == "car_number_ocr":
        return "training/car-number-labeling"
    if task_type in {"inspection_mark_ocr", "performance_mark_ocr"}:
        return f"training/inspection-ocr/{task_type}"
    if task_type in {"door_lock_state_detect", "connector_defect_detect"}:
        return f"training/inspection-state/{task_type}"
    return "training"


def _call_openai_compatible_planner(*, api_config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    base_url = str(api_config.get("base_url") or "").strip().rstrip("/")
    api_key = str(api_config.get("api_key") or "").strip()
    model_name = str(api_config.get("model_name") or "").strip()
    if not base_url or not api_key or not model_name:
        return None
    system_prompt = (
        "你是企业视觉平台里的流程引导助手。"
        "请根据用户目标、资产、现有模型和平台状态，给出一句概括、最多三条风险、以及一句最优下一步。"
        "只输出 JSON，键为 summary, risks, suggested_path。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    body = {
        "model": model_name,
        "messages": messages,
        "temperature": float(api_config.get("temperature") or 0.2),
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30.0, follow_redirects=True, trust_env=False) as client:
        resp = client.post(f"{base_url}/chat/completions", headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()
    content = payload.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        return None
    try:
        return json.loads(content)
    except Exception:
        return {"summary": str(content).strip()}


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
            path=_build_training_path(task_type),
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
                path=_build_training_path(task_type),
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

    llm_advice = None
    if llm_mode == "api" and api_config:
        try:
            llm_advice = _call_openai_compatible_planner(
                api_config=api_config,
                payload={
                    "goal": goal,
                    "task_type": task_type,
                    "task_label": _task_label(task_type),
                    "asset_file_names": [row.file_name for row in asset_rows][:5],
                    "released_model": released.model_code if released else None,
                    "submitted_model": submitted.model_code if submitted else None,
                    "approved_model": approved.model_code if approved else None,
                    "selected_local_model": llm_selection or {},
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
        "signals": signals,
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
