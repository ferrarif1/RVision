from __future__ import annotations

from typing import Any

from app.db.models import DataAsset, InferenceTask, ModelRecord, TrainingJob

_SYNTHETIC_TEXT_PREFIXES = ("api-", "api_", "qa-", "qa_", "quick-detect")
_SYNTHETIC_TEXT_FRAGMENTS = (
    "api-regression",
    "api_regression",
    "api-runtime",
    "api_runtime",
    "smoke",
)
_SYNTHETIC_MODEL_PREFIXES = ("api-", "api_", "qa_")


def _clean_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _has_synthetic_marker(*values: Any) -> bool:
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        if text.startswith(_SYNTHETIC_TEXT_PREFIXES):
            return True
        if any(fragment in text for fragment in _SYNTHETIC_TEXT_FRAGMENTS):
            return True
    return False


def is_synthetic_model_code(model_code: str | None) -> bool:
    return _clean_text(model_code).startswith(_SYNTHETIC_MODEL_PREFIXES)


def is_synthetic_model(model: ModelRecord | dict[str, Any] | None) -> bool:
    if not model:
        return False
    if isinstance(model, dict):
        return is_synthetic_model_code(model.get("model_code"))
    return is_synthetic_model_code(model.model_code)


def is_synthetic_asset(asset: DataAsset | dict[str, Any] | None) -> bool:
    if not asset:
        return False
    if isinstance(asset, dict):
        asset_type = _clean_text(asset.get("asset_type"))
        file_name = asset.get("file_name")
        storage_uri = asset.get("storage_uri")
        source_uri = asset.get("source_uri")
    else:
        asset_type = _clean_text(asset.asset_type)
        file_name = asset.file_name
        storage_uri = asset.storage_uri
        source_uri = asset.source_uri

    if asset_type == "screenshot":
        return True

    return _has_synthetic_marker(
        file_name,
        storage_uri,
        source_uri,
    )


def is_synthetic_training_job(
    job: TrainingJob | dict[str, Any] | None,
    *,
    base_model: ModelRecord | dict[str, Any] | None = None,
    candidate_model: ModelRecord | dict[str, Any] | None = None,
) -> bool:
    if not job:
        return False
    target_model_code = job.get("target_model_code") if isinstance(job, dict) else job.target_model_code

    return (
        is_synthetic_model_code(target_model_code)
        or is_synthetic_model(base_model)
        or is_synthetic_model(candidate_model)
    )


def is_synthetic_task(
    task: InferenceTask | dict[str, Any] | None,
    *,
    asset: DataAsset | dict[str, Any] | None = None,
    model: ModelRecord | dict[str, Any] | None = None,
) -> bool:
    if not task:
        return False

    return (
        is_synthetic_asset(asset)
        or is_synthetic_model(model)
    )
