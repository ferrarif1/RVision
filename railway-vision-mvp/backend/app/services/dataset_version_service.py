from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import DataAsset, DatasetVersion


def normalize_dataset_key(value: str, fallback: str = "dataset") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", str(value or "").strip().lower()).strip("-._")
    return (cleaned or fallback)[:128]


def _next_dataset_version(existing_versions: list[str]) -> str:
    max_seq = 0
    for value in existing_versions:
        match = re.fullmatch(r"v(\d+)", str(value or "").strip().lower())
        if match:
            max_seq = max(max_seq, int(match.group(1)))
    return f"v{max_seq + 1}"


def create_dataset_version_record(
    db: Session,
    *,
    asset: DataAsset,
    dataset_label: str,
    dataset_key: str | None = None,
    asset_purpose: str,
    source_type: str,
    summary: dict[str, Any],
    created_by: str,
) -> DatasetVersion:
    normalized_dataset_key = normalize_dataset_key(dataset_key or dataset_label)
    query = db.query(DatasetVersion).filter(DatasetVersion.dataset_key == normalized_dataset_key)
    if asset.buyer_tenant_id:
        query = query.filter(DatasetVersion.buyer_tenant_id == asset.buyer_tenant_id)
    else:
        query = query.filter(DatasetVersion.buyer_tenant_id.is_(None))

    version = _next_dataset_version([row.version for row in query.all()])
    dataset_version = DatasetVersion(
        id=str(uuid.uuid4()),
        dataset_key=normalized_dataset_key,
        dataset_label=dataset_label,
        version=version,
        asset_id=asset.id,
        asset_purpose=asset_purpose,
        buyer_tenant_id=asset.buyer_tenant_id,
        source_type=source_type,
        summary=summary,
        created_by=created_by,
    )
    db.add(dataset_version)
    db.flush()

    meta = dict(asset.meta or {})
    meta.update(
        {
            "dataset_key": normalized_dataset_key,
            "dataset_label": dataset_label,
            "dataset_version": version,
            "dataset_version_id": dataset_version.id,
            "dataset_source_type": source_type,
        }
    )
    asset.meta = meta
    db.add(asset)
    db.flush()
    return dataset_version
