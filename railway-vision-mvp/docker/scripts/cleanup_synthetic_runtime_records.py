from __future__ import annotations

import argparse
import json
import os
import shutil
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
    from app.db.models import DataAsset, DatasetVersion, InferenceResult, InferenceTask, ModelRecord, TrainingJob  # noqa: E402
    from app.services.data_hygiene_service import is_synthetic_asset  # noqa: E402
    from app.services.data_hygiene_service import is_synthetic_model  # noqa: E402
    from app.services.data_hygiene_service import is_synthetic_task  # noqa: E402
    from app.services.data_hygiene_service import is_synthetic_training_job  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host fallback path
    if "VISTRAL_CLEANUP_IN_CONTAINER" in os.environ:
        raise
    script_text = Path(__file__).read_text(encoding="utf-8")
    forwarded_args = " ".join(sys.argv[1:])
    subprocess.run(
        ["docker", "exec", "-i", "vistral_backend", "sh", "-lc", f"VISTRAL_CLEANUP_IN_CONTAINER=1 python - {forwarded_args}".strip()],
        input=script_text,
        text=True,
        check=True,
    )
    raise SystemExit(0) from exc


@dataclass
class CleanupPlan:
    synthetic_asset_ids: set[str]
    synthetic_dataset_version_ids: set[str]
    synthetic_task_ids: set[str]
    synthetic_result_ids: set[str]
    synthetic_model_ids: set[str]
    synthetic_training_job_ids: set[str]
    asset_paths: set[Path]
    model_paths: set[Path]
    screenshot_paths: set[Path]
    skipped_asset_ids: set[str]


def _resolve_runtime_path(raw: str | None) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([REPO_ROOT / path, Path("/app") / path])
    elif str(path).startswith("/app/"):
        relative = path.relative_to("/app")
        candidates.append(REPO_ROOT / relative)
        if relative.parts[:2] == ("app", "uploads"):
            candidates.append(REPO_ROOT / "backend" / relative)
        if relative.parts[:2] == ("app", "models_repo"):
            candidates.append(REPO_ROOT / "backend" / relative)
        if relative.parts and relative.parts[0] == "demo_data":
            candidates.append(REPO_ROOT / relative)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[-1].resolve()


def _is_referenced_elsewhere(path: Path, *, asset_rows: list[DataAsset], result_rows: list[InferenceResult], model_rows: list[ModelRecord]) -> bool:
    resolved = path.resolve()
    for row in asset_rows:
        candidate = _resolve_runtime_path(row.storage_uri)
        if candidate and candidate == resolved:
            return True
    for row in result_rows:
        candidate = _resolve_runtime_path(row.screenshot_uri)
        if candidate and candidate == resolved:
            return True
    for row in model_rows:
        for raw in (row.encrypted_uri, row.signature_uri, row.manifest_uri):
            candidate = _resolve_runtime_path(raw)
            if candidate and candidate == resolved:
                return True
    return False


def _collect_plan() -> CleanupPlan:
    session = SessionLocal()
    try:
        asset_rows = session.query(DataAsset).all()
        asset_map = {row.id: row for row in asset_rows}
        model_rows = session.query(ModelRecord).all()
        model_map = {row.id: row for row in model_rows}
        task_rows = session.query(InferenceTask).all()
        result_rows = session.query(InferenceResult).all()
        dataset_rows = session.query(DatasetVersion).all()
        training_rows = session.query(TrainingJob).all()

        synthetic_asset_ids = {row.id for row in asset_rows if is_synthetic_asset(row)}
        synthetic_model_ids = {row.id for row in model_rows if is_synthetic_model(row)}
        synthetic_task_ids = {
            row.id
            for row in task_rows
            if is_synthetic_task(row, asset=asset_map.get(row.asset_id), model=model_map.get(row.model_id))
        }
        synthetic_result_ids = {row.id for row in result_rows if row.task_id in synthetic_task_ids}
        synthetic_training_job_ids = {
            row.id
            for row in training_rows
            if is_synthetic_training_job(
                row,
                base_model=model_map.get(row.base_model_id),
                candidate_model=model_map.get(row.candidate_model_id),
            )
        }
        synthetic_dataset_version_ids = {
            row.id
            for row in dataset_rows
            if row.asset_id in synthetic_asset_ids or is_synthetic_asset(asset_map.get(row.asset_id))
        }

        real_task_asset_ids = {
            row.asset_id
            for row in task_rows
            if row.id not in synthetic_task_ids and row.asset_id
        }
        real_dataset_asset_ids = {
            row.asset_id
            for row in dataset_rows
            if row.id not in synthetic_dataset_version_ids and row.asset_id
        }
        skipped_asset_ids = {
            asset_id for asset_id in synthetic_asset_ids if asset_id in real_task_asset_ids or asset_id in real_dataset_asset_ids
        }
        asset_ids_to_delete = synthetic_asset_ids - skipped_asset_ids

        result_rows_to_delete = [row for row in result_rows if row.id in synthetic_result_ids]
        asset_rows_to_delete = [row for row in asset_rows if row.id in asset_ids_to_delete]
        model_rows_to_delete = [row for row in model_rows if row.id in synthetic_model_ids]

        asset_paths = {
            path
            for row in asset_rows_to_delete
            for path in [_resolve_runtime_path(row.storage_uri)]
            if path
        }
        screenshot_paths = {
            path
            for row in result_rows_to_delete
            for path in [_resolve_runtime_path(row.screenshot_uri)]
            if path
        }
        model_paths = {
            path
            for row in model_rows_to_delete
            for raw in (row.encrypted_uri, row.signature_uri, row.manifest_uri)
            for path in [_resolve_runtime_path(raw)]
            if path
        }

        return CleanupPlan(
            synthetic_asset_ids=asset_ids_to_delete,
            synthetic_dataset_version_ids=synthetic_dataset_version_ids,
            synthetic_task_ids=synthetic_task_ids,
            synthetic_result_ids=synthetic_result_ids,
            synthetic_model_ids=synthetic_model_ids,
            synthetic_training_job_ids=synthetic_training_job_ids,
            asset_paths=asset_paths,
            model_paths=model_paths,
            screenshot_paths=screenshot_paths,
            skipped_asset_ids=skipped_asset_ids,
        )
    finally:
        session.close()


def _remove_path(path: Path, *, apply: bool) -> bool:
    if not path.exists():
        return False
    if not apply:
        return True
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def execute_cleanup(*, apply: bool) -> dict[str, object]:
    plan = _collect_plan()
    session = SessionLocal()
    try:
        asset_rows = session.query(DataAsset).all()
        model_rows = session.query(ModelRecord).all()
        result_rows = session.query(InferenceResult).all()

        summary = {
            "apply": apply,
            "synthetic_assets": len(plan.synthetic_asset_ids),
            "synthetic_dataset_versions": len(plan.synthetic_dataset_version_ids),
            "synthetic_tasks": len(plan.synthetic_task_ids),
            "synthetic_results": len(plan.synthetic_result_ids),
            "synthetic_models": len(plan.synthetic_model_ids),
            "synthetic_training_jobs": len(plan.synthetic_training_job_ids),
            "skipped_assets": sorted(plan.skipped_asset_ids),
            "deleted_files": {"assets": 0, "models": 0, "screenshots": 0},
        }

        if not apply:
            summary["paths"] = {
                "assets": sorted(str(path.relative_to(REPO_ROOT)) for path in plan.asset_paths),
                "models": sorted(str(path.relative_to(REPO_ROOT)) for path in plan.model_paths),
                "screenshots": sorted(str(path.relative_to(REPO_ROOT)) for path in plan.screenshot_paths),
            }
            return summary

        if plan.synthetic_task_ids:
            session.query(InferenceTask).filter(InferenceTask.id.in_(plan.synthetic_task_ids)).delete(synchronize_session=False)
        if plan.synthetic_training_job_ids:
            session.query(TrainingJob).filter(TrainingJob.id.in_(plan.synthetic_training_job_ids)).delete(synchronize_session=False)
        if plan.synthetic_model_ids:
            session.query(ModelRecord).filter(ModelRecord.id.in_(plan.synthetic_model_ids)).delete(synchronize_session=False)
        if plan.synthetic_asset_ids:
            session.query(DataAsset).filter(DataAsset.id.in_(plan.synthetic_asset_ids)).delete(synchronize_session=False)
        session.commit()

        remaining_assets = session.query(DataAsset).all()
        remaining_models = session.query(ModelRecord).all()
        remaining_results = session.query(InferenceResult).all()

        for path in sorted(plan.asset_paths):
            if not _is_referenced_elsewhere(path, asset_rows=remaining_assets, result_rows=remaining_results, model_rows=remaining_models):
                summary["deleted_files"]["assets"] += int(_remove_path(path, apply=True))
        for path in sorted(plan.model_paths):
            if not _is_referenced_elsewhere(path, asset_rows=remaining_assets, result_rows=remaining_results, model_rows=remaining_models):
                summary["deleted_files"]["models"] += int(_remove_path(path, apply=True))
        for path in sorted(plan.screenshot_paths):
            if not _is_referenced_elsewhere(path, asset_rows=remaining_assets, result_rows=remaining_results, model_rows=remaining_models):
                summary["deleted_files"]["screenshots"] += int(_remove_path(path, apply=True))

        return summary
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete synthetic runtime DB records and their orphan files.")
    parser.add_argument("--apply", action="store_true", help="Actually delete records and files.")
    args = parser.parse_args()
    print(json.dumps(execute_cleanup(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
