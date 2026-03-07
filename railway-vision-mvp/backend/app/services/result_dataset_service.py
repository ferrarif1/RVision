from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import DataAsset, InferenceResult, InferenceTask
from app.security.dependencies import AuthUser
from app.security.roles import is_buyer_user

MEDIA_ASSET_TYPES = {"image", "video"}
DATASET_EXPORT_ALLOWED_PURPOSES = {"training", "validation", "finetune"}
RESULT_DATASET_SCHEMA_VERSION = "visionhub.result_dataset.v1"
DATASET_PREVIEW_LIMIT = 20


@dataclass(slots=True)
class ResultDatasetExportArtifact:
    asset: DataAsset
    summary: dict[str, Any]


def _safe_label_fragment(value: str, fallback: str = "dataset") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", str(value or "").strip()).strip("-._")
    return (cleaned or fallback)[:80]


def _safe_zip_member_name(file_name: str) -> str:
    base = os.path.basename(str(file_name or "").strip())
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", base).strip("._")
    return cleaned or "asset.bin"


def _task_result_focus(rows: list[InferenceResult]) -> InferenceResult | None:
    if not rows:
        return None
    for row in rows:
        result_json = row.result_json if isinstance(row.result_json, dict) else {}
        if result_json.get("stage") == "expert" and result_json.get("task_type") == "object_detect":
            return row
    for row in rows:
        result_json = row.result_json if isinstance(row.result_json, dict) else {}
        if result_json.get("stage") == "final":
            return row
    return rows[0]


def _load_task_bundle(
    db: Session,
    task_id: str,
    *,
    current_user: AuthUser,
) -> tuple[InferenceTask, DataAsset, InferenceResult, list[InferenceResult]]:
    task = db.query(InferenceTask).filter(InferenceTask.id == task_id).first()
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    if is_buyer_user(current_user.roles) and task.buyer_tenant_id != current_user.tenant_id:
        raise ValueError(f"Task not found: {task_id}")
    if not task.asset_id:
        raise ValueError(f"Task has no source asset: {task_id}")

    asset = db.query(DataAsset).filter(DataAsset.id == task.asset_id).first()
    if not asset:
        raise ValueError(f"Source asset not found for task: {task_id}")
    if is_buyer_user(current_user.roles) and asset.buyer_tenant_id != current_user.tenant_id:
        raise ValueError(f"Source asset not found for task: {task_id}")
    if asset.asset_type not in MEDIA_ASSET_TYPES:
        raise ValueError(f"Task source asset is not image/video: {task_id}")
    if not os.path.exists(asset.storage_uri):
        raise ValueError(f"Source asset file missing for task: {task_id}")

    rows = db.query(InferenceResult).filter(InferenceResult.task_id == task_id).order_by(InferenceResult.created_at.asc()).all()
    if is_buyer_user(current_user.roles):
        rows = [row for row in rows if row.buyer_tenant_id == current_user.tenant_id]
    focus = _task_result_focus(rows)
    if not focus:
        raise ValueError(f"Task has no results yet: {task_id}")
    return task, asset, focus, rows


def export_tasks_to_dataset_asset(
    db: Session,
    *,
    current_user: AuthUser,
    task_ids: list[str],
    asset_purpose: str,
    dataset_label: str,
    include_screenshots: bool,
) -> ResultDatasetExportArtifact:
    if asset_purpose not in DATASET_EXPORT_ALLOWED_PURPOSES:
        raise ValueError("asset_purpose must be training, validation or finetune")
    clean_task_ids = []
    seen_task_ids: set[str] = set()
    for task_id in task_ids:
        clean = str(task_id or "").strip()
        if clean and clean not in seen_task_ids:
            seen_task_ids.add(clean)
            clean_task_ids.append(clean)
    if not clean_task_ids:
        raise ValueError("task_ids is required")

    bundles = [_load_task_bundle(db, task_id, current_user=current_user) for task_id in clean_task_ids]
    buyer_tenant_ids = {task.buyer_tenant_id for task, _, _, _ in bundles}
    if len(buyer_tenant_ids) > 1:
        raise ValueError("task_ids must belong to the same buyer tenant")
    unique_assets = {asset.id: asset for _, asset, _, _ in bundles}

    settings = get_settings()
    export_dir = os.path.join(settings.asset_repo_path, "generated_datasets")
    os.makedirs(export_dir, exist_ok=True)

    export_asset_id = str(uuid.uuid4())
    dataset_stem = _safe_label_fragment(dataset_label, fallback=f"result-dataset-{asset_purpose}")
    zip_path = os.path.join(export_dir, f"{export_asset_id}.zip")

    task_records: list[dict[str, Any]] = []
    label_vocab: set[str] = set()
    preview_members: list[str] = []
    unique_asset_members: dict[str, str] = {}
    screenshot_members = 0

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for task, asset, focus, rows in bundles:
            if asset.id not in unique_asset_members:
                asset_member = f"assets/{asset.id}_{_safe_zip_member_name(asset.file_name)}"
                zf.write(asset.storage_uri, asset_member)
                unique_asset_members[asset.id] = asset_member
                if len(preview_members) < DATASET_PREVIEW_LIMIT:
                    preview_members.append(asset_member)

            result_json = focus.result_json if isinstance(focus.result_json, dict) else {}
            predictions = result_json.get("predictions") if isinstance(result_json.get("predictions"), list) else []
            auto_predictions = result_json.get("auto_predictions") if isinstance(result_json.get("auto_predictions"), list) else []
            manual_review = result_json.get("manual_review") if isinstance(result_json.get("manual_review"), dict) else {}
            for prediction in predictions:
                label = str((prediction or {}).get("label") or "").strip()
                if label:
                    label_vocab.add(label)

            screenshot_member = None
            if include_screenshots and focus.screenshot_uri and os.path.exists(focus.screenshot_uri):
                screenshot_member = f"previews/{focus.id}.jpg"
                zf.write(focus.screenshot_uri, screenshot_member)
                screenshot_members += 1

            record = {
                "sample_id": task.id,
                "task_id": task.id,
                "result_id": focus.id,
                "asset_id": asset.id,
                "asset_type": asset.asset_type,
                "source_file": unique_asset_members[asset.id],
                "preview_file": screenshot_member,
                "source_file_name": asset.file_name,
                "task_type": task.task_type,
                "object_prompt": result_json.get("object_prompt"),
                "object_count": result_json.get("object_count", len(predictions)),
                "matched_labels": result_json.get("matched_labels") or [],
                "predictions": predictions,
                "auto_predictions": auto_predictions,
                "review_status": result_json.get("review_status"),
                "manual_review": manual_review,
                "result_summary": {
                    "alert_level": focus.alert_level,
                    "duration_ms": focus.duration_ms,
                    "model_id": focus.model_id,
                    "model_hash": focus.model_hash,
                },
                "all_result_ids": [row.id for row in rows],
                "generated_at": datetime.utcnow().isoformat(),
            }
            task_records.append(record)

            zf.writestr(
                f"annotations/{task.id}.json",
                json.dumps(record, ensure_ascii=False, indent=2),
            )

        zf.writestr(
            "annotations/records.jsonl",
            "\n".join(json.dumps(record, ensure_ascii=False) for record in task_records) + "\n",
        )
        zf.writestr("labels.txt", "\n".join(sorted(label_vocab)) + ("\n" if label_vocab else ""))
        manifest = {
            "schema_version": RESULT_DATASET_SCHEMA_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "dataset_label": dataset_label,
            "asset_purpose": asset_purpose,
            "task_count": len(task_records),
            "resource_count": len(unique_asset_members),
            "label_vocab": sorted(label_vocab),
            "include_screenshots": include_screenshots,
            "tasks": [
                {
                    "task_id": record["task_id"],
                    "asset_id": record["asset_id"],
                    "source_file": record["source_file"],
                    "preview_file": record["preview_file"],
                    "object_prompt": record["object_prompt"],
                    "object_count": record["object_count"],
                    "review_status": record["review_status"],
                }
                for record in task_records
            ],
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    checksum = hashlib.sha256()
    with open(zip_path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            checksum.update(chunk)
    file_size = os.path.getsize(zip_path)

    meta = {
        "size": file_size,
        "extension": ".zip",
        "asset_purpose": asset_purpose,
        "dataset_label": dataset_label,
        "use_case": "quick-detect-dataset-export",
        "intended_model_code": "object_detect",
        "archive_kind": "result_annotation_bundle",
        "archive_entry_count": len(unique_asset_members) + len(task_records) + 3 + screenshot_members,
        "archive_file_count": len(unique_asset_members) + len(task_records) + 3 + screenshot_members,
        "archive_directory_count": 3,
        "archive_resource_count": len(unique_asset_members),
        "archive_image_count": sum(1 for asset in unique_assets.values() if asset.asset_type == "image"),
        "archive_video_count": sum(1 for asset in unique_assets.values() if asset.asset_type == "video"),
        "archive_ignored_entry_count": len(task_records) + 2 + screenshot_members,
        "archive_max_depth": 1,
        "archive_preview_members": preview_members,
        "archive_uncompressed_bytes": sum(os.path.getsize(asset.storage_uri) for asset in unique_assets.values()),
        "export_schema": RESULT_DATASET_SCHEMA_VERSION,
        "source_task_ids": clean_task_ids,
        "source_result_count": len(task_records),
        "label_vocab": sorted(label_vocab),
        "include_screenshots": include_screenshots,
    }

    asset = DataAsset(
        id=export_asset_id,
        file_name=f"{dataset_stem}.zip",
        asset_type="archive",
        storage_uri=zip_path,
        source_uri=f"visionhub://results/export-dataset/{export_asset_id}",
        sensitivity_level="L2",
        checksum=checksum.hexdigest(),
        buyer_tenant_id=next(iter(buyer_tenant_ids)),
        meta=meta,
        uploaded_by=current_user.id,
    )
    db.add(asset)
    db.flush()

    summary = {
        "task_count": len(task_records),
        "resource_count": len(unique_asset_members),
        "label_vocab": sorted(label_vocab),
        "include_screenshots": include_screenshots,
        "source_task_ids": clean_task_ids,
        "reviewed_task_count": sum(1 for record in task_records if record.get("review_status") == "revised"),
    }
    return ResultDatasetExportArtifact(asset=asset, summary=summary)
