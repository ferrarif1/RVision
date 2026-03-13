from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import MODEL_TYPE_EXPERT
from app.core.constants import MODEL_STATUS_RELEASED
from app.db.models import DataAsset, ModelRecord, ModelRelease
from app.security.dependencies import AuthUser
from app.security.roles import is_buyer_user

TASK_CATALOG_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "config" / "railcar_inspection_task_catalog.json",
    Path("/app/config/railcar_inspection_task_catalog.json"),
)

DEFAULT_TASK_TYPE_LABELS = {
    "object_detect": "快速识别",
    "car_number_ocr": "车号识别",
    "inspection_mark_ocr": "定检标记识别",
    "performance_mark_ocr": "性能标记识别",
    "door_lock_state_detect": "门锁状态识别",
    "connector_defect_detect": "连接件缺陷识别",
    "bolt_missing_detect": "螺栓缺失",
}

DEFAULT_TASK_TYPE_KEYWORDS = {
    "object_detect": (
        "object",
        "objects",
        "detect",
        "detection",
        "find object",
        "box",
        "bbox",
        "locate",
        "label",
        "annotate",
        "segment",
        "car",
        "vehicle",
        "bus",
        "person",
        "people",
        "human",
        "pedestrian",
        "train",
        "locomotive",
        "wagon",
        "truck",
        "motorbike",
        "bicycle",
        "boat",
        "bottle",
        "chair",
        "dog",
        "cat",
        "horse",
        "sheep",
        "tv",
        "monitor",
        "目标",
        "检测",
        "框选",
        "框出来",
        "标注",
        "识别物体",
        "识别目标",
        "找目标",
        "找物体",
        "车辆",
        "行人",
        "人员",
        "列车",
        "火车",
    ),
    "car_number_ocr": (
        "plate",
        "number",
        "ocr",
        "car_number",
        "wagon number",
        "wagon no",
        "car id",
        "railcar number",
        "serial number",
        "车号",
        "车厢号",
        "车皮号",
        "车牌",
        "车次",
        "编号",
        "号码",
        "数字编号",
        "车号内容",
        "车号文字",
        "货车号",
        "货车编号",
        "车体编号",
        "识别车号",
        "读取车号",
        "ocr车号",
    ),
    "inspection_mark_ocr": (
        "inspection mark",
        "inspection",
        "maintenance mark",
        "检修记录",
        "定检标记",
        "检修标记",
        "定检日期",
        "厂修标记",
        "段修标记",
    ),
    "performance_mark_ocr": (
        "performance mark",
        "performance",
        "性能标记",
        "性能文字",
        "性能代码",
        "标记文字",
    ),
    "door_lock_state_detect": (
        "door lock",
        "lock state",
        "door state",
        "门锁",
        "锁闭",
        "敞开",
        "门状态",
    ),
    "connector_defect_detect": (
        "connector",
        "connector defect",
        "coupler",
        "连接件",
        "连接件缺陷",
        "松动",
        "变形",
        "缺失",
    ),
    "bolt_missing_detect": (
        "bolt",
        "missing",
        "screw",
        "fastener",
        "loose",
        "螺栓",
        "螺母",
        "缺失",
        "紧固件",
        "松动",
        "脱落",
        "检测螺栓",
    ),
}


@lru_cache(maxsize=1)
def _load_task_catalog_payload() -> dict[str, Any]:
    config_path = next((path for path in TASK_CATALOG_CANDIDATES if path.exists()), None)
    if config_path is None:
        return {"tasks": {}}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {"tasks": {}}
    if not isinstance(payload, dict):
        return {"tasks": {}}
    return payload


def _task_catalog_tasks() -> dict[str, dict[str, Any]]:
    payload = _load_task_catalog_payload()
    tasks = payload.get("tasks") if isinstance(payload.get("tasks"), dict) else {}
    return {str(key): value for key, value in tasks.items() if isinstance(value, dict)}


TASK_TYPE_LABELS = {
    **DEFAULT_TASK_TYPE_LABELS,
    **{
        task_type: str(meta.get("label") or DEFAULT_TASK_TYPE_LABELS.get(task_type) or task_type)
        for task_type, meta in _task_catalog_tasks().items()
    },
}

TASK_TYPE_KEYWORDS = {
    **DEFAULT_TASK_TYPE_KEYWORDS,
    **{
        task_type: tuple(
            dict.fromkeys(
                [
                    *(DEFAULT_TASK_TYPE_KEYWORDS.get(task_type, ()) or ()),
                    *[str(item).strip().lower() for item in meta.get("keywords") or [] if str(item).strip()],
                ]
            )
        )
        for task_type, meta in _task_catalog_tasks().items()
    },
}


def task_type_from_model(model: ModelRecord) -> str | None:
    manifest = model.manifest if isinstance(model.manifest, dict) else {}
    if getattr(model, "model_type", MODEL_TYPE_EXPERT) != MODEL_TYPE_EXPERT:
        return None
    task_type = manifest.get("task_type")
    return str(task_type).strip() if task_type else None


@dataclass
class ModelRouteCandidate:
    model_id: str
    model_code: str
    version: str
    model_hash: str
    task_type: str
    score: int
    reasons: list[str]
    target_devices: list[str]
    target_buyers: list[str]
    created_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_code": self.model_code,
            "version": self.version,
            "model_hash": self.model_hash,
            "task_type": self.task_type,
            "task_type_label": TASK_TYPE_LABELS.get(self.task_type, self.task_type),
            "score": self.score,
            "reasons": self.reasons,
            "target_devices": self.target_devices,
            "target_buyers": self.target_buyers,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class ModelRoutingDecision:
    engine: str
    requested_task_type: str | None
    inferred_task_type: str | None
    confidence: str
    summary: str
    signals: list[str]
    selected_model: ModelRouteCandidate | None
    alternatives: list[ModelRouteCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "requested_task_type": self.requested_task_type,
            "inferred_task_type": self.inferred_task_type,
            "confidence": self.confidence,
            "summary": self.summary,
            "signals": self.signals,
            "selected_model": self.selected_model.to_dict() if self.selected_model else None,
            "alternatives": [item.to_dict() for item in self.alternatives],
        }


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _collect_signal_texts(asset: DataAsset, requested_task_type: str | None, intent_text: str | None) -> list[str]:
    texts = [
        _normalize_text(intent_text),
        _normalize_text(asset.file_name),
        _normalize_text(asset.source_uri),
        _normalize_text(requested_task_type),
        _normalize_text(TASK_TYPE_LABELS.get(requested_task_type or "", "")),
    ]
    meta = asset.meta if isinstance(asset.meta, dict) else {}
    for key, value in meta.items():
        if isinstance(value, (str, int, float)):
            texts.append(_normalize_text(f"{key}:{value}"))
    return [value for value in texts if value]


def _find_matching_release(
    db: Session,
    model_id: str,
    *,
    buyer_code: str | None,
    device_code: str | None,
) -> ModelRelease | None:
    releases = (
        db.query(ModelRelease)
        .filter(ModelRelease.model_id == model_id, ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .all()
    )
    for release in releases:
        buyers = release.target_buyers or []
        devices = release.target_devices or []
        buyer_ok = not buyer_code or not buyers or buyer_code in buyers
        device_ok = not device_code or not devices or device_code in devices
        if buyer_ok and device_ok:
            return release
    return None


def _list_schedulable_models(
    db: Session,
    current_user: AuthUser,
    *,
    device_code: str | None,
) -> list[tuple[ModelRecord, ModelRelease]]:
    rows = db.query(ModelRecord).filter(ModelRecord.status == MODEL_STATUS_RELEASED).order_by(ModelRecord.created_at.desc()).all()
    buyer_code = current_user.tenant_code if is_buyer_user(current_user.roles) else None

    candidates: list[tuple[ModelRecord, ModelRelease]] = []
    for model in rows:
        if getattr(model, "model_type", MODEL_TYPE_EXPERT) != MODEL_TYPE_EXPERT:
            continue
        release = _find_matching_release(db, model.id, buyer_code=buyer_code, device_code=device_code)
        if not release:
            continue
        candidates.append((model, release))
    return candidates


def _infer_task_type(texts: list[str], requested_task_type: str | None, available_task_types: set[str]) -> tuple[str | None, list[str]]:
    signals: list[str] = []
    if requested_task_type:
        signals.append(f"收到显式任务类型：{TASK_TYPE_LABELS.get(requested_task_type, requested_task_type)}")
        return requested_task_type, signals

    scores = {task_type: 0 for task_type in available_task_types}
    matched_terms: dict[str, set[str]] = {task_type: set() for task_type in available_task_types}

    for text in texts:
        for task_type in available_task_types:
            for keyword in TASK_TYPE_KEYWORDS.get(task_type, ()):
                if keyword in text:
                    scores[task_type] += 1
                    matched_terms[task_type].add(keyword)

    inferred = None
    best_score = 0
    for task_type, score in scores.items():
        if score > best_score:
            inferred = task_type
            best_score = score

    if inferred and best_score > 0:
        terms = sorted(matched_terms[inferred])
        signals.append(f"语义路由命中关键词：{', '.join(terms[:5])}")
        return inferred, signals

    if len(available_task_types) == 1:
        only = next(iter(available_task_types))
        signals.append("当前可调度模型只覆盖一个任务类型，自动采用该类型。")
        return only, signals

    signals.append("未识别到稳定语义信号，将按最新可用模型排序。")
    return None, signals


def _keyword_matches(task_type: str, texts: list[str]) -> set[str]:
    matches: set[str] = set()
    for text in texts:
        for keyword in TASK_TYPE_KEYWORDS.get(task_type, ()):
            if keyword in text:
                matches.add(keyword)
    return matches


def _is_canonical_task_model(model: ModelRecord, task_type: str) -> bool:
    return str(model.model_code or "").strip() == str(task_type or "").strip()


def _build_summary(
    *,
    requested_task_type: str | None,
    inferred_task_type: str | None,
    selected_model: ModelRouteCandidate | None,
    signals: list[str],
) -> str:
    if not selected_model:
        return "主模型调度未找到可用小模型。"

    task_label = TASK_TYPE_LABELS.get(inferred_task_type or requested_task_type or selected_model.task_type, selected_model.task_type)
    reason = signals[0] if signals else "未提供额外语义信号"
    return f"主模型调度基于“{task_label}”意图选择小模型 {selected_model.model_code} {selected_model.version}。{reason}"


def _confidence_from_score(score: int, signal_count: int) -> str:
    if score >= 90 or signal_count >= 2:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def recommend_small_models(
    db: Session,
    current_user: AuthUser,
    *,
    asset: DataAsset,
    device_code: str | None,
    requested_task_type: str | None,
    intent_text: str | None,
    limit: int = 3,
) -> ModelRoutingDecision:
    schedulable = _list_schedulable_models(db, current_user, device_code=device_code)
    if not schedulable:
        return ModelRoutingDecision(
            engine="local-llm-router",
            requested_task_type=requested_task_type,
            inferred_task_type=requested_task_type,
            confidence="low",
            summary="当前没有已发布且可调度的小模型。",
            signals=["无可用 RELEASED 模型"],
            selected_model=None,
            alternatives=[],
        )

    texts = _collect_signal_texts(asset, requested_task_type, intent_text)
    available_task_types = {
        task_type
        for model, _ in schedulable
        for task_type in [task_type_from_model(model)]
        if task_type
    }
    inferred_task_type, signals = _infer_task_type(texts, requested_task_type, available_task_types)

    ranked: list[ModelRouteCandidate] = []
    for recency_index, (model, release) in enumerate(schedulable):
        task_type = task_type_from_model(model)
        if not task_type:
            continue
        if requested_task_type and task_type != requested_task_type:
            continue

        reasons: list[str] = []
        score = 0

        if _is_canonical_task_model(model, task_type):
            score += 28
            reasons.append("标准任务模型编码与任务类型一致")
        else:
            score -= 14
            reasons.append("候选模型编码与标准任务类型不一致")

        if inferred_task_type and task_type == inferred_task_type:
            score += 70
            reasons.append(f"任务类型匹配：{TASK_TYPE_LABELS.get(task_type, task_type)}")
        elif inferred_task_type and task_type != inferred_task_type:
            score -= 20
            reasons.append("任务类型不是主模型优先推断结果")

        matches = sorted(_keyword_matches(task_type, texts))
        if matches:
            score += min(len(matches) * 12, 36)
            reasons.append(f"关键词命中：{', '.join(matches[:4])}")

        if not release.target_devices:
            score += 5
            reasons.append("设备范围为通配发布")
        elif device_code and device_code in (release.target_devices or []):
            score += 10
            reasons.append(f"已发布到设备 {device_code}")

        if is_buyer_user(current_user.roles):
            if not release.target_buyers:
                score += 5
                reasons.append("买家范围为通配发布")
            elif current_user.tenant_code and current_user.tenant_code in (release.target_buyers or []):
                score += 10
                reasons.append(f"已发布到买家 {current_user.tenant_code}")

        if recency_index < 4:
            bonus = 4 - recency_index
            score += bonus
            reasons.append("版本较新")

        ranked.append(
            ModelRouteCandidate(
                model_id=model.id,
                model_code=model.model_code,
                version=model.version,
                model_hash=model.model_hash,
                task_type=task_type,
                score=score,
                reasons=reasons or ["默认按最近发布模型排序"],
                target_devices=release.target_devices or [],
                target_buyers=release.target_buyers or [],
                created_at=model.created_at,
            )
        )

    ranked.sort(key=lambda item: (item.score, item.created_at or datetime.min), reverse=True)
    selected = ranked[0] if ranked else None
    summary = _build_summary(
        requested_task_type=requested_task_type,
        inferred_task_type=inferred_task_type,
        selected_model=selected,
        signals=signals,
    )

    return ModelRoutingDecision(
        engine="local-llm-router",
        requested_task_type=requested_task_type,
        inferred_task_type=inferred_task_type or requested_task_type,
        confidence=_confidence_from_score(selected.score if selected else 0, len(signals)),
        summary=summary,
        signals=signals,
        selected_model=selected,
        alternatives=ranked[: max(1, limit)],
    )


def latest_schedulable_models_by_task_type(
    db: Session,
    current_user: AuthUser,
    *,
    device_code: str | None,
    task_types: set[str] | None = None,
) -> dict[str, ModelRouteCandidate]:
    schedulable = _list_schedulable_models(db, current_user, device_code=device_code)
    latest: dict[str, ModelRouteCandidate] = {}
    for model, release in schedulable:
        task_type = task_type_from_model(model)
        if not task_type:
            continue
        if task_types and task_type not in task_types:
            continue
        candidate = ModelRouteCandidate(
            model_id=model.id,
            model_code=model.model_code,
            version=model.version,
            model_hash=model.model_hash,
            task_type=task_type,
            score=0,
            reasons=["按任务类型选择当前最新可调度模型"],
            target_devices=release.target_devices or [],
            target_buyers=release.target_buyers or [],
            created_at=model.created_at,
        )
        current = latest.get(task_type)
        if not current:
            latest[task_type] = candidate
            continue
        current_exact_match = current.model_code == task_type
        next_exact_match = model.model_code == task_type
        if next_exact_match and not current_exact_match:
            latest[task_type] = candidate
            continue
        if next_exact_match == current_exact_match and (candidate.created_at or datetime.min) > (current.created_at or datetime.min):
            latest[task_type] = candidate
    return latest
