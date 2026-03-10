from datetime import datetime, timedelta
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import MODEL_STATUS_APPROVED
from app.core.constants import MODEL_STATUS_RELEASED
from app.core.constants import MODEL_STATUS_SUBMITTED
from app.core.constants import TASK_STATUS_DISPATCHED
from app.core.constants import TASK_STATUS_FAILED
from app.core.constants import TASK_STATUS_PENDING
from app.core.constants import TASK_STATUS_SUCCEEDED
from app.core.constants import TRAINING_JOB_STATUS_FAILED
from app.core.constants import TRAINING_JOB_STATUS_PENDING
from app.core.constants import TRAINING_JOB_STATUS_RUNNING
from app.core.constants import TRAINING_JOB_STATUS_SUCCEEDED
from app.db.database import get_db
from app.db.models import AuditLog, DataAsset, Device, InferenceResult, InferenceTask, ModelRecord, ModelRelease, TrainingJob
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import MODEL_READ_ROLES, is_buyer_user, is_platform_user, is_supplier_user
from app.services.data_hygiene_service import is_synthetic_asset
from app.services.data_hygiene_service import is_synthetic_model
from app.services.data_hygiene_service import is_synthetic_task
from app.services.data_hygiene_service import is_synthetic_training_job

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
REPO_ROOT = Path(__file__).resolve().parents[3]


def _existing_path(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_json_count(path: Path | None, key: str) -> int:
    if not path:
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    value = payload.get(key)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_nested_json_count(path: Path | None, *keys: str) -> int:
    if not path:
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    value = payload
    for key in keys:
        if not isinstance(value, dict):
            return 0
        value = value.get(key)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _count_local_train_images() -> int:
    train_dir = _existing_path(REPO_ROOT / "demo_data" / "train", Path("/app/demo_data/train"))
    if not train_dir:
        return 0
    return sum(1 for path in train_dir.iterdir() if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"})


def _released_model_ids_for_buyer(db: Session, buyer_code: str | None) -> set[str]:
    rows = (
        db.query(ModelRelease)
        .filter(ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .all()
    )
    model_ids: set[str] = set()
    for row in rows:
        targets = row.target_buyers or []
        if not targets or (buyer_code and buyer_code in targets):
            model_ids.add(row.model_id)
    return model_ids


def _device_in_buyer_scope(device_code: str, releases: list[ModelRelease], buyer_code: str | None) -> bool:
    for release in releases:
        target_devices = release.target_devices or []
        if target_devices and device_code not in target_devices:
            continue
        targets = release.target_buyers or []
        if not targets or (buyer_code and buyer_code in targets):
            return True
    return False


@router.get("/summary")
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    assets_query = db.query(DataAsset)
    tasks_query = db.query(InferenceTask)
    results_query = db.query(InferenceResult)
    models_query = db.query(ModelRecord)
    training_jobs_query = db.query(TrainingJob)

    buyer_code = current_user.tenant_code
    buyer_tenant_id = current_user.tenant_id
    released_for_buyer = set()

    if is_buyer_user(current_user.roles):
        assets_query = assets_query.filter(DataAsset.buyer_tenant_id == buyer_tenant_id)
        tasks_query = tasks_query.filter(InferenceTask.buyer_tenant_id == buyer_tenant_id)
        results_query = results_query.filter(InferenceResult.buyer_tenant_id == buyer_tenant_id)
        released_for_buyer = _released_model_ids_for_buyer(db, buyer_code)
        if released_for_buyer:
            models_query = models_query.filter(ModelRecord.id.in_(released_for_buyer))
        else:
            models_query = models_query.filter(ModelRecord.id == "__none__")
        training_jobs_query = training_jobs_query.filter(TrainingJob.id == "__none__")
    elif is_supplier_user(current_user.roles):
        # Supplier dashboard focuses on model/training collaboration only.
        assets_query = assets_query.filter(DataAsset.id == "__none__")
        tasks_query = tasks_query.filter(InferenceTask.id == "__none__")
        results_query = results_query.filter(InferenceResult.id == "__none__")
        models_query = models_query.filter(ModelRecord.owner_tenant_id == current_user.tenant_id)
        training_jobs_query = training_jobs_query.filter(TrainingJob.owner_tenant_id == current_user.tenant_id)

    asset_rows = assets_query.order_by(DataAsset.created_at.desc()).all()
    curated_assets = [row for row in asset_rows if not is_synthetic_asset(row)]
    asset_map = {row.id: row for row in asset_rows}

    model_rows = models_query.order_by(ModelRecord.created_at.desc()).all()
    curated_models = [row for row in model_rows if not is_synthetic_model(row)]
    model_map = {row.id: row for row in model_rows}

    task_rows = tasks_query.order_by(InferenceTask.created_at.desc()).all()
    missing_task_asset_ids = {row.asset_id for row in task_rows if row.asset_id and row.asset_id not in asset_map}
    if missing_task_asset_ids:
        for row in db.query(DataAsset).filter(DataAsset.id.in_(missing_task_asset_ids)).all():
            asset_map[row.id] = row
    missing_task_model_ids = {row.model_id for row in task_rows if row.model_id and row.model_id not in model_map}
    if missing_task_model_ids:
        for row in db.query(ModelRecord).filter(ModelRecord.id.in_(missing_task_model_ids)).all():
            model_map[row.id] = row
    curated_tasks = [
        row
        for row in task_rows
        if not is_synthetic_task(row, asset=asset_map.get(row.asset_id), model=model_map.get(row.model_id))
    ]

    training_rows = training_jobs_query.order_by(TrainingJob.created_at.desc()).all()
    missing_training_model_ids = {
        model_id
        for row in training_rows
        for model_id in (row.base_model_id, row.candidate_model_id)
        if model_id and model_id not in model_map
    }
    if missing_training_model_ids:
        for row in db.query(ModelRecord).filter(ModelRecord.id.in_(missing_training_model_ids)).all():
            model_map[row.id] = row
    curated_training_jobs = [
        row
        for row in training_rows
        if not is_synthetic_training_job(
            row,
            base_model=model_map.get(row.base_model_id),
            candidate_model=model_map.get(row.candidate_model_id),
        )
    ]

    visible_task_ids = {row.id for row in curated_tasks}
    result_rows = results_query.order_by(InferenceResult.created_at.desc()).all()
    curated_results = [row for row in result_rows if row.task_id in visible_task_ids]

    assets_total = len(curated_assets)
    models_submitted = sum(1 for row in curated_models if row.status == MODEL_STATUS_SUBMITTED)
    models_approved = sum(1 for row in curated_models if row.status == MODEL_STATUS_APPROVED)
    models_released = sum(1 for row in curated_models if row.status == MODEL_STATUS_RELEASED)
    training_pending = sum(1 for row in curated_training_jobs if row.status == TRAINING_JOB_STATUS_PENDING)
    training_running = sum(1 for row in curated_training_jobs if row.status == TRAINING_JOB_STATUS_RUNNING)
    training_succeeded = sum(1 for row in curated_training_jobs if row.status == TRAINING_JOB_STATUS_SUCCEEDED)
    training_failed = sum(1 for row in curated_training_jobs if row.status == TRAINING_JOB_STATUS_FAILED)
    tasks_pending = sum(1 for row in curated_tasks if row.status == TASK_STATUS_PENDING)
    tasks_dispatched = sum(1 for row in curated_tasks if row.status == TASK_STATUS_DISPATCHED)
    tasks_succeeded = sum(1 for row in curated_tasks if row.status == TASK_STATUS_SUCCEEDED)
    tasks_failed = sum(1 for row in curated_tasks if row.status == TASK_STATUS_FAILED)
    results_total = len(curated_results)

    releases = (
        db.query(ModelRelease)
        .filter(ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .all()
    )
    devices = db.query(Device).order_by(Device.created_at.desc()).all()
    now = datetime.utcnow()
    online_before = now - timedelta(seconds=90)
    visible_devices = devices
    if is_buyer_user(current_user.roles):
        visible_devices = [device for device in devices if _device_in_buyer_scope(device.code, releases, buyer_code)]
    elif is_supplier_user(current_user.roles):
        visible_devices = []
    devices_online = sum(1 for device in visible_devices if device.last_seen_at and device.last_seen_at >= online_before)

    recent_assets_rows = curated_assets[:5]
    recent_models_rows = curated_models[:5]
    recent_tasks_rows = curated_tasks[:5]

    audits_24h = 0
    if is_platform_user(current_user.roles):
        audits_24h = (
            db.query(AuditLog)
            .filter(AuditLog.created_at >= now - timedelta(hours=24))
            .count()
        )

    demo_assets = sum(1 for row in curated_assets if str(row.source_uri or "").startswith("demo://"))
    ocr_export_assets = sum(1 for row in curated_assets if str(row.source_uri or "").startswith("vistral://training/car-number-labeling/"))
    labeling_summary_path = _existing_path(
        REPO_ROOT / "demo_data" / "generated_datasets" / "car_number_ocr_labeling" / "summary.json",
        Path("/app/demo_data/generated_datasets/car_number_ocr_labeling/summary.json"),
    )
    text_summary_path = _existing_path(
        REPO_ROOT / "demo_data" / "generated_datasets" / "car_number_ocr_text_dataset" / "car_number_ocr_text_dataset_summary.json",
        Path("/app/demo_data/generated_datasets/car_number_ocr_text_dataset/car_number_ocr_text_dataset_summary.json"),
    )

    return {
        "role_view": (
            "platform"
            if is_platform_user(current_user.roles)
            else "supplier"
            if is_supplier_user(current_user.roles)
            else "buyer"
        ),
        "lanes": {
            "line1_assets": {
                "total_assets": assets_total,
            },
            "line2_models_training": {
                "models_submitted": models_submitted,
                "models_approved": models_approved,
                "models_released": models_released,
                "training_pending": training_pending,
                "training_running": training_running,
                "training_succeeded": training_succeeded,
                "training_failed": training_failed,
            },
            "line3_execution": {
                "tasks_pending": tasks_pending,
                "tasks_dispatched": tasks_dispatched,
                "tasks_succeeded": tasks_succeeded,
                "tasks_failed": tasks_failed,
                "results_total": results_total,
            },
            "line4_governance_delivery": {
                "devices_total": len(visible_devices),
                "devices_online": devices_online,
                "audits_24h": audits_24h,
            },
        },
        "recent": {
            "assets": [
                {
                    "id": row.id,
                    "file_name": row.file_name,
                    "asset_type": row.asset_type,
                    "created_at": row.created_at,
                    "asset_purpose": (row.meta or {}).get("asset_purpose") if isinstance(row.meta, dict) else None,
                }
                for row in recent_assets_rows
            ],
            "models": [
                {
                    "id": row.id,
                    "model_code": row.model_code,
                    "version": row.version,
                    "status": row.status,
                    "created_at": row.created_at,
                }
                for row in recent_models_rows
            ],
            "tasks": [
                {
                    "id": row.id,
                    "task_type": row.task_type,
                    "status": row.status,
                    "created_at": row.created_at,
                }
                for row in recent_tasks_rows
            ],
        },
        "real_data": {
            "demo_assets": demo_assets,
            "ocr_export_assets": ocr_export_assets,
            "local_train_images": _count_local_train_images(),
            "labeling_rows": _load_json_count(labeling_summary_path, "annotated_rows"),
            "text_train_rows": _load_nested_json_count(text_summary_path, "bundles", "train", "sample_count"),
            "text_validation_rows": _load_nested_json_count(text_summary_path, "bundles", "validation", "sample_count"),
        },
        "hygiene": {
            "hidden_assets": max(len(asset_rows) - len(curated_assets), 0),
            "hidden_models": max(len(model_rows) - len(curated_models), 0),
            "hidden_tasks": max(len(task_rows) - len(curated_tasks), 0),
            "hidden_results": max(len(result_rows) - len(curated_results), 0),
            "hidden_training_jobs": max(len(training_rows) - len(curated_training_jobs), 0),
        },
    }
