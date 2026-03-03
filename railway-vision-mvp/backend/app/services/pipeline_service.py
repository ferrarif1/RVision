from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import MODEL_TYPE_EXPERT
from app.core.constants import MODEL_TYPE_ROUTER
from app.core.constants import MODEL_TYPES
from app.core.constants import PIPELINE_STATUS_RELEASED
from app.db.models import ModelRecord, ModelRelease, PipelineRecord
from app.security.dependencies import AuthUser
from app.security.roles import is_buyer_user, is_platform_user, is_supplier_user


DEFAULT_MODEL_INPUTS = {
    "media": ["image", "frames"],
    "context": ["scene_hint", "device_type", "camera_id", "job_id", "timestamp"],
    "options": ["thresholds", "max_experts", "return_intermediate"],
}

DEFAULT_EXPERT_OUTPUTS = {
    "predictions": ["label", "score", "bbox", "mask", "text", "attributes"],
    "artifacts": ["preview_frame", "roi_crop", "heatmap", "feature_summary"],
    "metrics": ["duration_ms", "gpu_mem_mb", "version", "calibration"],
}

DEFAULT_ROUTER_OUTPUTS = {
    "scene_id": "string",
    "scene_score": "float",
    "tasks": "list[string]",
    "task_scores": "list[float]",
}


@dataclass(slots=True)
class PipelineCatalog:
    pipeline: PipelineRecord
    router: ModelRecord | None
    models: dict[str, ModelRecord]


def normalize_model_inputs(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and raw:
        return raw
    if isinstance(raw, str) and raw.strip():
        return {"media": [part.strip() for part in raw.split("|") if part.strip()], "context": DEFAULT_MODEL_INPUTS["context"], "options": DEFAULT_MODEL_INPUTS["options"]}
    return dict(DEFAULT_MODEL_INPUTS)


def normalize_model_outputs(model_type: str, raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and raw:
        return raw
    if isinstance(raw, str) and raw.strip():
        return {"schema": raw}
    if model_type == MODEL_TYPE_ROUTER:
        return dict(DEFAULT_ROUTER_OUTPUTS)
    return dict(DEFAULT_EXPERT_OUTPUTS)


def build_model_registry_payload(model: ModelRecord) -> dict[str, Any]:
    manifest = model.manifest if isinstance(model.manifest, dict) else {}
    model_type = model.model_type if model.model_type in MODEL_TYPES else MODEL_TYPE_EXPERT
    return {
        "id": model.id,
        "model_code": model.model_code,
        "version": model.version,
        "model_hash": model.model_hash,
        "model_type": model_type,
        "task_type": manifest.get("task_type"),
        "runtime": model.runtime or manifest.get("runtime") or manifest.get("model_format") or "bin",
        "plugin_name": model.plugin_name or manifest.get("plugin_name") or manifest.get("task_type") or model.model_code,
        "inputs": normalize_model_inputs(model.inputs or manifest.get("inputs") or manifest.get("input_schema")),
        "outputs": normalize_model_outputs(model_type, model.outputs or manifest.get("outputs") or manifest.get("output_schema")),
        "gpu_mem_mb": model.gpu_mem_mb,
        "latency_ms": model.latency_ms,
        "owner_tenant_id": model.owner_tenant_id,
        "created_at": model.created_at,
    }


def _release_scope(pipeline: PipelineRecord) -> dict[str, Any]:
    config = pipeline.config if isinstance(pipeline.config, dict) else {}
    release = config.get("release")
    return release if isinstance(release, dict) else {}


def serialize_pipeline(pipeline: PipelineRecord, router: ModelRecord | None, models: dict[str, ModelRecord]) -> dict[str, Any]:
    release = _release_scope(pipeline)
    normalized_config, normalized_experts, normalized_thresholds, normalized_fusion = normalize_pipeline_config(
        router_model_id=pipeline.router_model_id,
        expert_map=pipeline.expert_map or {},
        thresholds=pipeline.thresholds or {},
        fusion_rules=pipeline.fusion_rules or {},
        config=pipeline.config or {},
    )
    return {
        "id": pipeline.id,
        "pipeline_code": pipeline.pipeline_code,
        "name": pipeline.name,
        "version": pipeline.version,
        "status": pipeline.status,
        "router_model_id": pipeline.router_model_id,
        "router_model_code": router.model_code if router else None,
        "router": normalized_config.get("router") or {},
        "experts": normalized_experts,
        "thresholds": normalized_thresholds,
        "fusion": normalized_fusion,
        "pre": normalized_config.get("pre") or {},
        "post": normalized_config.get("post") or {},
        "human_review": normalized_config.get("human_review") or {},
        "threshold_version": normalized_config.get("threshold_version"),
        "expert_map": normalized_experts,
        "fusion_rules": normalized_fusion,
        "config": normalized_config,
        "target_devices": release.get("target_devices") or [],
        "target_buyers": release.get("target_buyers") or [],
        "traffic_ratio": release.get("traffic_ratio", 100),
        "models": [build_model_registry_payload(model) for model in models.values()],
        "created_at": pipeline.created_at,
    }


def _normalize_expert_bindings(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    normalized: dict[str, list[dict[str, Any]]] = {}
    for task_key, items in (raw or {}).items():
        bucket: list[dict[str, Any]] = []
        for index, item in enumerate(items or []):
            if isinstance(item, str):
                bucket.append({"model_id": item, "priority": index + 1})
            elif isinstance(item, dict) and item.get("model_id"):
                bucket.append(
                    {
                        "model_id": item["model_id"],
                        "priority": int(item.get("priority", index + 1)),
                        "min_score": item.get("min_score"),
                        "role": item.get("role", "expert"),
                    }
                )
        if bucket:
            normalized[str(task_key)] = bucket
    return normalized


def normalize_pipeline_config(
    *,
    router_model_id: str | None,
    expert_map: dict[str, Any],
    thresholds: dict[str, Any],
    fusion_rules: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    base = dict(config or {})
    router = base.get("router") if isinstance(base.get("router"), dict) else {}
    normalized_experts = _normalize_expert_bindings(expert_map or base.get("experts") or {})
    normalized_thresholds = dict(thresholds or base.get("thresholds") or {})
    normalized_fusion = dict(fusion_rules or base.get("fusion") or {})

    base["router"] = {
        **router,
        "model_id": router_model_id or router.get("model_id"),
        "scene_whitelist": list(router.get("scene_whitelist") or []),
        "scene_blacklist": list(router.get("scene_blacklist") or []),
        "fallback": router.get("fallback") or {"mode": "human_review", "expand_top_k": 2},
    }
    base["experts"] = normalized_experts
    base["thresholds"] = normalized_thresholds
    base["fusion"] = normalized_fusion or {"strategy": "priority", "max_experts_per_task": 2}
    base["pre"] = base.get("pre") if isinstance(base.get("pre"), dict) else {}
    base["post"] = base.get("post") if isinstance(base.get("post"), dict) else {}
    base["human_review"] = base.get("human_review") if isinstance(base.get("human_review"), dict) else {"enabled": True, "conditions": []}
    base.setdefault("threshold_version", "thresholds-v1")
    base.setdefault("release", {"target_devices": [], "target_buyers": [], "traffic_ratio": 100})
    return base, normalized_experts, normalized_thresholds, normalized_fusion


def collect_pipeline_model_ids(pipeline: PipelineRecord | dict[str, Any]) -> list[str]:
    if isinstance(pipeline, PipelineRecord):
        router_model_id = pipeline.router_model_id
        config = pipeline.config if isinstance(pipeline.config, dict) else {}
        expert_map = pipeline.expert_map or {}
    else:
        router_model_id = ((pipeline or {}).get("router") or {}).get("model_id")
        config = pipeline if isinstance(pipeline, dict) else {}
        expert_map = config.get("experts") or {}

    model_ids: list[str] = []
    if router_model_id:
        model_ids.append(router_model_id)
    for items in (expert_map or {}).values():
        for item in items or []:
            if isinstance(item, str):
                model_ids.append(item)
            elif isinstance(item, dict) and item.get("model_id"):
                model_ids.append(item["model_id"])
    seen: set[str] = set()
    ordered: list[str] = []
    for model_id in model_ids:
        if model_id and model_id not in seen:
            ordered.append(model_id)
            seen.add(model_id)
    return ordered


def get_pipeline_catalog(db: Session, pipeline: PipelineRecord) -> PipelineCatalog:
    model_ids = collect_pipeline_model_ids(pipeline)
    rows = db.query(ModelRecord).filter(ModelRecord.id.in_(model_ids)).all() if model_ids else []
    model_map = {row.id: row for row in rows}
    router = model_map.get(pipeline.router_model_id) if pipeline.router_model_id else None
    return PipelineCatalog(pipeline=pipeline, router=router, models=model_map)


def validate_pipeline_models(db: Session, pipeline_config: dict[str, Any], model_ids: list[str]) -> dict[str, ModelRecord]:
    rows = db.query(ModelRecord).filter(ModelRecord.id.in_(model_ids)).all() if model_ids else []
    model_map = {row.id: row for row in rows}
    missing = [model_id for model_id in model_ids if model_id not in model_map]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Pipeline references unknown models: {', '.join(missing)}")

    router_id = ((pipeline_config.get("router") or {}).get("model_id")) if isinstance(pipeline_config, dict) else None
    if router_id:
        router = model_map[router_id]
        if router.model_type not in {MODEL_TYPE_ROUTER}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="router_model_id must reference a router model")

    for task_key, bindings in (pipeline_config.get("experts") or {}).items():
        if not bindings:
            continue
        for binding in bindings:
            model_id = binding.get("model_id")
            if not model_id:
                continue
            model = model_map[model_id]
            if model.model_type != MODEL_TYPE_EXPERT:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Expert binding for {task_key} must reference expert models")
    return model_map


def pipeline_visible_to_user(pipeline: PipelineRecord, current_user: AuthUser, *, device_code: str | None = None) -> bool:
    if is_platform_user(current_user.roles):
        return True
    if is_supplier_user(current_user.roles):
        return pipeline.owner_tenant_id == current_user.tenant_id
    if not is_buyer_user(current_user.roles):
        return False
    if pipeline.status != PIPELINE_STATUS_RELEASED:
        return False
    release = _release_scope(pipeline)
    target_buyers = release.get("target_buyers") or []
    target_devices = release.get("target_devices") or []
    buyer_ok = not target_buyers or (current_user.tenant_code and current_user.tenant_code in target_buyers)
    device_ok = not device_code or not target_devices or device_code in target_devices
    return buyer_ok and device_ok


def get_accessible_pipeline_or_404(db: Session, current_user: AuthUser, pipeline_id: str, *, device_code: str | None = None) -> PipelineRecord:
    pipeline = db.query(PipelineRecord).filter(PipelineRecord.id == pipeline_id).first()
    if not pipeline or not pipeline_visible_to_user(pipeline, current_user, device_code=device_code):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return pipeline


def model_released_to_scope(db: Session, model_id: str, *, buyer_code: str | None, device_code: str | None) -> bool:
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
            return True
    return False
