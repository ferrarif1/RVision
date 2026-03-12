from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
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
    from app.db.models import DataAsset  # noqa: E402
    from app.db.models import DatasetVersion  # noqa: E402
    from app.db.models import InferenceResult  # noqa: E402
    from app.db.models import InferenceRun  # noqa: E402
    from app.db.models import InferenceTask  # noqa: E402
    from app.db.models import ModelRecord  # noqa: E402
    from app.db.models import ModelRelease  # noqa: E402
    from app.db.models import PipelineRecord  # noqa: E402
    from app.db.models import ReviewQueue  # noqa: E402
    from app.db.models import TrainingJob  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host fallback path
    if "VISTRAL_KEEP_DEMO_CHAIN_IN_CONTAINER" in os.environ:
        raise
    script_text = Path(__file__).read_text(encoding="utf-8")
    forwarded_args = " ".join(sys.argv[1:])
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "vistral_backend",
            "sh",
            "-lc",
            f"VISTRAL_KEEP_DEMO_CHAIN_IN_CONTAINER=1 python - {forwarded_args}".strip(),
        ],
        input=script_text,
        text=True,
        check=True,
    )
    raise SystemExit(0) from exc


CURRENT_RELEASED_CODES = {
    "car_number_ocr",
    "object_detect",
    "bolt_missing_detect",
    "scene_router",
}
PIPELINE_CODE_TO_KEEP = "demo-inspection-pipeline"
ORIGINAL_CAR_NUMBER_JOB_CODE = "train-577ce47c10"


@dataclass
class KeepDecision:
    keep_model_ids: set[str]
    keep_training_job_ids: set[str]
    keep_asset_ids: set[str]
    keep_dataset_version_ids: set[str]
    keep_task_ids: set[str]
    keep_result_ids: set[str]
    keep_run_ids: set[str]
    keep_review_queue_ids: set[str]
    keep_pipeline_ids: set[str]
    keep_pipeline_updates: list[dict[str, object]]
    keep_reasons: dict[str, list[dict[str, str]]]


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


def _serialize_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(row) for row in rows]


def _latest_released_by_code(session) -> dict[str, ModelRecord]:
    selected: dict[str, ModelRecord] = {}
    for code in CURRENT_RELEASED_CODES:
        row = (
            session.query(ModelRecord)
            .filter(ModelRecord.model_code == code, ModelRecord.status == "RELEASED")
            .order_by(ModelRecord.created_at.desc())
            .first()
        )
        if row:
            selected[code] = row
    return selected


def _build_keep_decision(session) -> KeepDecision:
    keep_reasons: dict[str, list[dict[str, str]]] = {
        "models": [],
        "training_jobs": [],
        "assets": [],
        "dataset_versions": [],
        "tasks": [],
        "results": [],
        "pipelines": [],
    }

    keep_model_ids: set[str] = set()
    keep_training_job_ids: set[str] = set()
    keep_asset_ids: set[str] = set()
    keep_dataset_version_ids: set[str] = set()
    keep_task_ids: set[str] = set()
    keep_result_ids: set[str] = set()
    keep_run_ids: set[str] = set()
    keep_review_queue_ids: set[str] = set()
    keep_pipeline_ids: set[str] = set()
    keep_pipeline_updates: list[dict[str, object]] = []

    current_models = _latest_released_by_code(session)
    for code, model in current_models.items():
        keep_model_ids.add(model.id)
        keep_reasons["models"].append(
            {
                "id": model.id,
                "label": f"{model.model_code}:{model.version}",
                "reason": "保留当前已发布模型",
            }
        )

    current_car_model = current_models.get("car_number_ocr")
    if current_car_model:
        job = (
            session.query(TrainingJob)
            .filter(TrainingJob.candidate_model_id == current_car_model.id)
            .order_by(TrainingJob.created_at.desc())
            .first()
        )
        if job:
            keep_training_job_ids.add(job.id)
            keep_reasons["training_jobs"].append(
                {"id": job.id, "label": job.job_code, "reason": "保留当前车号模型的训练来源"}
            )
            for asset_id in (job.asset_ids or []) + (job.validation_asset_ids or []):
                if asset_id:
                    keep_asset_ids.add(str(asset_id))

    original_job = session.query(TrainingJob).filter(TrainingJob.job_code == ORIGINAL_CAR_NUMBER_JOB_CODE).first()
    if original_job:
        keep_training_job_ids.add(original_job.id)
        keep_reasons["training_jobs"].append(
            {"id": original_job.id, "label": original_job.job_code, "reason": "保留车号示例原始训练素材来源"}
        )
        for asset_id in (original_job.asset_ids or []) + (original_job.validation_asset_ids or []):
            if asset_id:
                keep_asset_ids.add(str(asset_id))

    dataset_rows = session.query(DatasetVersion).all()
    for row in dataset_rows:
        if row.asset_id in keep_asset_ids:
            keep_dataset_version_ids.add(row.id)
            keep_reasons["dataset_versions"].append(
                {
                    "id": row.id,
                    "label": f"{row.dataset_key}:{row.version}",
                    "reason": "与保留训练素材直接关联",
                }
            )

    asset_map = {row.id: row for row in session.query(DataAsset).all()}
    task_rows = session.query(InferenceTask).order_by(InferenceTask.created_at.desc()).all()
    latest_task_by_model_asset: dict[tuple[str, str], InferenceTask] = {}
    for task in task_rows:
        if not (task.model_id and task.model_id in keep_model_ids and task.asset_id):
            continue
        if str(task.status or "").upper() != "SUCCEEDED":
            continue
        asset = asset_map.get(task.asset_id)
        if not asset:
            continue
        lowered_name = str(asset.file_name or "").lower()
        if lowered_name.startswith(("api-", "api_")):
            continue
        key = (task.model_id, asset.file_name)
        if key not in latest_task_by_model_asset:
            latest_task_by_model_asset[key] = task

    for task in latest_task_by_model_asset.values():
        keep_task_ids.add(task.id)
        if task.asset_id:
            keep_asset_ids.add(task.asset_id)
        keep_reasons["tasks"].append(
            {"id": task.id, "label": task.task_type, "reason": "保留当前模型按样本去重后的最新验证/推理记录"}
        )

    pipeline = (
        session.query(PipelineRecord)
        .filter(PipelineRecord.pipeline_code == PIPELINE_CODE_TO_KEEP, PipelineRecord.status == "RELEASED")
        .order_by(PipelineRecord.created_at.desc())
        .first()
    )
    if pipeline:
        keep_pipeline_ids.add(pipeline.id)
        keep_reasons["pipelines"].append(
            {"id": pipeline.id, "label": f"{pipeline.pipeline_code}:{pipeline.version}", "reason": "保留当前演示流水线"}
        )
        current_router = current_models.get("scene_router")
        current_bolt = current_models.get("bolt_missing_detect")
        updated_expert_map = dict(pipeline.expert_map or {})
        if current_car_model:
            updated_expert_map["car_number_ocr"] = [
                {
                    "role": "expert",
                    "model_id": current_car_model.id,
                    "priority": 1,
                    "min_score": None,
                }
            ]
        if current_bolt:
            keep_model_ids.add(current_bolt.id)
            updated_expert_map["bolt_missing_detect"] = [
                {
                    "role": "expert",
                    "model_id": current_bolt.id,
                    "priority": 1,
                    "min_score": None,
                }
            ]
        if current_router:
            keep_model_ids.add(current_router.id)
        keep_pipeline_updates.append(
            {
                "pipeline_id": pipeline.id,
                "router_model_id": current_router.id if current_router else pipeline.router_model_id,
                "expert_map": updated_expert_map,
            }
        )
    result_rows = session.query(InferenceResult).all()
    for row in result_rows:
        if row.task_id in keep_task_ids:
            keep_result_ids.add(row.id)
            keep_reasons["results"].append(
                {"id": row.id, "label": row.task_id, "reason": "与保留任务关联"}
            )

    for run in session.query(InferenceRun).all():
        if run.task_id in keep_task_ids:
            keep_run_ids.add(run.id)
    for row in session.query(ReviewQueue).all():
        if row.task_id in keep_task_ids:
            keep_review_queue_ids.add(row.id)

    for asset_id in sorted(keep_asset_ids):
        asset = asset_map.get(asset_id)
        if asset:
            keep_reasons["assets"].append(
                {"id": asset.id, "label": asset.file_name, "reason": "保留当前模型/训练链直接引用资产"}
            )

    return KeepDecision(
        keep_model_ids=keep_model_ids,
        keep_training_job_ids=keep_training_job_ids,
        keep_asset_ids=keep_asset_ids,
        keep_dataset_version_ids=keep_dataset_version_ids,
        keep_task_ids=keep_task_ids,
        keep_result_ids=keep_result_ids,
        keep_run_ids=keep_run_ids,
        keep_review_queue_ids=keep_review_queue_ids,
        keep_pipeline_ids=keep_pipeline_ids,
        keep_pipeline_updates=keep_pipeline_updates,
        keep_reasons=keep_reasons,
    )


def _delete_file_candidates(*, rows: list[dict[str, object]], field_names: tuple[str, ...]) -> set[Path]:
    paths: set[Path] = set()
    for row in rows:
        for field in field_names:
            raw = row.get(field)
            path = _resolve_runtime_path(raw)
            if path:
                paths.add(path)
    return paths


def collect_plan() -> dict[str, object]:
    session = SessionLocal()
    try:
        keep = _build_keep_decision(session)

        all_models = session.query(ModelRecord).all()
        all_jobs = session.query(TrainingJob).all()
        all_assets = session.query(DataAsset).all()
        all_dataset_versions = session.query(DatasetVersion).all()
        all_tasks = session.query(InferenceTask).all()
        all_results = session.query(InferenceResult).all()
        all_runs = session.query(InferenceRun).all()
        all_reviews = session.query(ReviewQueue).all()
        all_pipelines = session.query(PipelineRecord).all()

        delete_models = [row for row in all_models if row.id not in keep.keep_model_ids]
        delete_jobs = [row for row in all_jobs if row.id not in keep.keep_training_job_ids]
        delete_dataset_versions = [row for row in all_dataset_versions if row.id not in keep.keep_dataset_version_ids]
        delete_tasks = [row for row in all_tasks if row.id not in keep.keep_task_ids]
        delete_results = [row for row in all_results if row.id not in keep.keep_result_ids]
        delete_runs = [row for row in all_runs if row.id not in keep.keep_run_ids]
        delete_reviews = [row for row in all_reviews if row.id not in keep.keep_review_queue_ids]
        delete_pipelines = [row for row in all_pipelines if row.id not in keep.keep_pipeline_ids]
        delete_assets = [row for row in all_assets if row.id not in keep.keep_asset_ids]

        return {
            "keep": {
                "models": _serialize_rows(keep.keep_reasons["models"]),
                "training_jobs": _serialize_rows(keep.keep_reasons["training_jobs"]),
                "assets": _serialize_rows(keep.keep_reasons["assets"]),
                "dataset_versions": _serialize_rows(keep.keep_reasons["dataset_versions"]),
                "tasks": _serialize_rows(keep.keep_reasons["tasks"]),
                "results": _serialize_rows(keep.keep_reasons["results"]),
                "pipelines": _serialize_rows(keep.keep_reasons["pipelines"]),
                "pipeline_updates": keep.keep_pipeline_updates,
            },
            "delete": {
                "models": [
                    {
                        "id": row.id,
                        "model_code": row.model_code,
                        "version": row.version,
                        "status": row.status,
                    }
                    for row in delete_models
                ],
                "training_jobs": [
                    {
                        "id": row.id,
                        "job_code": row.job_code,
                        "target_model_code": row.target_model_code,
                        "status": row.status,
                    }
                    for row in delete_jobs
                ],
                "dataset_versions": [
                    {
                        "id": row.id,
                        "dataset_key": row.dataset_key,
                        "version": row.version,
                        "asset_id": row.asset_id,
                    }
                    for row in delete_dataset_versions
                ],
                "assets": [
                    {
                        "id": row.id,
                        "file_name": row.file_name,
                        "asset_type": row.asset_type,
                        "storage_uri": row.storage_uri,
                    }
                    for row in delete_assets
                ],
                "tasks": [
                    {
                        "id": row.id,
                        "task_type": row.task_type,
                        "status": row.status,
                        "model_id": row.model_id,
                        "pipeline_id": row.pipeline_id,
                    }
                    for row in delete_tasks
                ],
                "results": [
                    {"id": row.id, "task_id": row.task_id, "model_id": row.model_id, "screenshot_uri": row.screenshot_uri}
                    for row in delete_results
                ],
                "runs": [{"id": row.id, "task_id": row.task_id} for row in delete_runs],
                "review_queue": [{"id": row.id, "task_id": row.task_id} for row in delete_reviews],
                "pipelines": [
                    {"id": row.id, "pipeline_code": row.pipeline_code, "version": row.version}
                    for row in delete_pipelines
                ],
            },
            "file_candidates": {
                "asset_files": sorted(
                    str(path.relative_to(REPO_ROOT))
                    for path in _delete_file_candidates(
                        rows=[
                            {
                                "storage_uri": row.storage_uri,
                            }
                            for row in delete_assets
                        ],
                        field_names=("storage_uri",),
                    )
                    if path.exists() and str(path).startswith(str(REPO_ROOT))
                ),
                "model_files": sorted(
                    str(path.relative_to(REPO_ROOT))
                    for path in _delete_file_candidates(
                        rows=[
                            {
                                "encrypted_uri": row.encrypted_uri,
                                "signature_uri": row.signature_uri,
                                "manifest_uri": row.manifest_uri,
                            }
                            for row in delete_models
                        ],
                        field_names=("encrypted_uri", "signature_uri", "manifest_uri"),
                    )
                    if path.exists() and str(path).startswith(str(REPO_ROOT))
                ),
                "screenshot_files": sorted(
                    str(path.relative_to(REPO_ROOT))
                    for path in _delete_file_candidates(
                        rows=[{"screenshot_uri": row.screenshot_uri} for row in delete_results],
                        field_names=("screenshot_uri",),
                    )
                    if path.exists() and str(path).startswith(str(REPO_ROOT))
                ),
            },
            "summary": {
                "keep_models": len(keep.keep_model_ids),
                "keep_training_jobs": len(keep.keep_training_job_ids),
                "keep_assets": len(keep.keep_asset_ids),
                "keep_dataset_versions": len(keep.keep_dataset_version_ids),
                "keep_tasks": len(keep.keep_task_ids),
                "keep_results": len(keep.keep_result_ids),
                "keep_pipelines": len(keep.keep_pipeline_ids),
                "delete_models": len(delete_models),
                "delete_training_jobs": len(delete_jobs),
                "delete_assets": len(delete_assets),
                "delete_dataset_versions": len(delete_dataset_versions),
                "delete_tasks": len(delete_tasks),
                "delete_results": len(delete_results),
                "delete_runs": len(delete_runs),
                "delete_review_queue": len(delete_reviews),
                "delete_pipelines": len(delete_pipelines),
            },
        }
    finally:
        session.close()


def execute_apply(plan: dict[str, object]) -> dict[str, object]:
    session = SessionLocal()
    try:
        for update in plan["keep"]["pipeline_updates"]:
            row = session.query(PipelineRecord).filter(PipelineRecord.id == update["pipeline_id"]).first()
            if row:
                row.router_model_id = update["router_model_id"]
                row.expert_map = update["expert_map"]

        delete = plan["delete"]
        delete_task_ids = [row["id"] for row in delete["tasks"]]
        delete_run_ids = [row["id"] for row in delete["runs"]]
        delete_review_ids = [row["id"] for row in delete["review_queue"]]
        delete_job_ids = [row["id"] for row in delete["training_jobs"]]
        delete_pipeline_ids = [row["id"] for row in delete["pipelines"]]
        delete_model_ids = [row["id"] for row in delete["models"]]
        delete_dataset_version_ids = [row["id"] for row in delete["dataset_versions"]]
        delete_asset_ids = [row["id"] for row in delete["assets"]]

        if delete_run_ids:
            session.query(InferenceRun).filter(InferenceRun.id.in_(delete_run_ids)).delete(synchronize_session=False)
        if delete_review_ids:
            session.query(ReviewQueue).filter(ReviewQueue.id.in_(delete_review_ids)).delete(synchronize_session=False)
        if delete_task_ids:
            session.query(InferenceTask).filter(InferenceTask.id.in_(delete_task_ids)).delete(synchronize_session=False)
        if delete_job_ids:
            session.query(TrainingJob).filter(TrainingJob.id.in_(delete_job_ids)).delete(synchronize_session=False)
        if delete_pipeline_ids:
            session.query(PipelineRecord).filter(PipelineRecord.id.in_(delete_pipeline_ids)).delete(synchronize_session=False)
        if delete_model_ids:
            session.query(ModelRecord).filter(ModelRecord.id.in_(delete_model_ids)).delete(synchronize_session=False)
        if delete_dataset_version_ids:
            session.query(DatasetVersion).filter(DatasetVersion.id.in_(delete_dataset_version_ids)).delete(synchronize_session=False)
        if delete_asset_ids:
            session.query(DataAsset).filter(DataAsset.id.in_(delete_asset_ids)).delete(synchronize_session=False)
        session.commit()

        deleted_files = {"asset_files": 0, "model_files": 0, "screenshot_files": 0}
        for key in deleted_files:
            for rel in plan["file_candidates"][key]:
                path = REPO_ROOT / rel
                if path.exists():
                    path.unlink()
                    deleted_files[key] += 1
        return {"applied": True, "deleted_files": deleted_files, "summary": plan["summary"]}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep current car-number/object-detect demo chain and prune historical records.")
    parser.add_argument("--apply", action="store_true", help="Actually delete historical records/files.")
    args = parser.parse_args()

    plan = collect_plan()
    if args.apply:
        print(json.dumps(execute_apply(plan), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
