from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if "__file__" in globals():
    try:
        REPO_ROOT = Path(__file__).resolve().parents[2]
    except IndexError:
        REPO_ROOT = Path("/app")
else:
    REPO_ROOT = Path("/app")
BACKEND_ROOT = REPO_ROOT / "backend" if (REPO_ROOT / "backend").exists() else REPO_ROOT
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from app.db.database import SessionLocal  # noqa: E402
    from app.db.models import DataAsset, DatasetVersion, TrainingJob  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host fallback path
    if "VISTRAL_PRUNE_IN_CONTAINER" in os.environ:
        raise
    script_text = Path(__file__).read_text(encoding="utf-8")
    forwarded_args = " ".join(sys.argv[1:])
    subprocess.run(
        ["docker", "exec", "-i", "vistral_backend", "sh", "-lc", f"VISTRAL_PRUNE_IN_CONTAINER=1 python - {forwarded_args}".strip()],
        input=script_text,
        text=True,
        check=True,
    )
    raise SystemExit(0) from exc


TARGET_DATASET_KEYS = {
    "local-car-number-ocr-text-train",
    "local-car-number-ocr-text-validation",
}


@dataclass
class PruneRow:
    dataset_key: str
    version_id: str
    version: str
    asset_id: str
    file_name: str
    storage_uri: str


def _collect_prune_rows(*, keep_latest: int) -> tuple[list[PruneRow], dict[str, int]]:
    session = SessionLocal()
    try:
        rows: list[PruneRow] = []
        counts: dict[str, int] = {}
        referenced_asset_ids: set[str] = set()
        for job in session.query(TrainingJob).all():
            for asset_id in (job.asset_ids or []):
                if asset_id:
                    referenced_asset_ids.add(str(asset_id))
            for asset_id in (job.validation_asset_ids or []):
                if asset_id:
                    referenced_asset_ids.add(str(asset_id))
        for dataset_key in sorted(TARGET_DATASET_KEYS):
            versions = (
                session.query(DatasetVersion)
                .filter(DatasetVersion.dataset_key == dataset_key)
                .order_by(DatasetVersion.created_at.desc())
                .all()
            )
            counts[dataset_key] = len(versions)
            for row in versions[keep_latest:]:
                asset = session.query(DataAsset).filter(DataAsset.id == row.asset_id).first()
                if not asset:
                    continue
                if str(asset.id) in referenced_asset_ids:
                    continue
                rows.append(
                    PruneRow(
                        dataset_key=dataset_key,
                        version_id=row.id,
                        version=row.version,
                        asset_id=asset.id,
                        file_name=asset.file_name,
                        storage_uri=asset.storage_uri,
                    )
                )
        return rows, counts
    finally:
        session.close()


def execute_prune(*, keep_latest: int, apply: bool) -> dict[str, object]:
    prune_rows, counts = _collect_prune_rows(keep_latest=keep_latest)
    summary: dict[str, object] = {
        "apply": apply,
        "keep_latest": keep_latest,
        "dataset_counts": counts,
        "prune_dataset_versions": len(prune_rows),
        "prune_assets": len({row.asset_id for row in prune_rows}),
        "deleted_files": 0,
        "rows": [
            {
                "dataset_key": row.dataset_key,
                "version_id": row.version_id,
                "version": row.version,
                "asset_id": row.asset_id,
                "file_name": row.file_name,
                "storage_uri": row.storage_uri,
            }
            for row in prune_rows
        ],
    }
    if not apply:
        return summary

    session = SessionLocal()
    try:
        asset_ids = {row.asset_id for row in prune_rows}
        version_ids = {row.version_id for row in prune_rows}
        session.query(DatasetVersion).filter(DatasetVersion.id.in_(version_ids)).delete(synchronize_session=False)
        session.query(DataAsset).filter(DataAsset.id.in_(asset_ids)).delete(synchronize_session=False)
        session.commit()

        deleted_files = 0
        for row in prune_rows:
            raw = str(row.storage_uri or "").strip()
            if not raw:
                continue
            path = Path(raw)
            if str(path).startswith("/app/"):
                path = REPO_ROOT / path.relative_to("/app")
            if path.exists():
                path.unlink()
                deleted_files += 1
        summary["deleted_files"] = deleted_files
        summary.pop("rows", None)
        return summary
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune superseded OCR text export dataset versions/assets.")
    parser.add_argument("--keep-latest", type=int, default=3, help="How many latest versions to keep per dataset key")
    parser.add_argument("--apply", action="store_true", help="Actually delete old dataset versions/assets")
    args = parser.parse_args()
    result = execute_prune(keep_latest=max(args.keep_latest, 1), apply=bool(args.apply))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
