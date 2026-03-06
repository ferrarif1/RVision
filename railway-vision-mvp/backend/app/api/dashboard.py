from datetime import datetime, timedelta

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

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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

    assets_total = assets_query.count()
    models_submitted = models_query.filter(ModelRecord.status == MODEL_STATUS_SUBMITTED).count()
    models_approved = models_query.filter(ModelRecord.status == MODEL_STATUS_APPROVED).count()
    models_released = models_query.filter(ModelRecord.status == MODEL_STATUS_RELEASED).count()
    training_pending = training_jobs_query.filter(TrainingJob.status == TRAINING_JOB_STATUS_PENDING).count()
    training_running = training_jobs_query.filter(TrainingJob.status == TRAINING_JOB_STATUS_RUNNING).count()
    training_succeeded = training_jobs_query.filter(TrainingJob.status == TRAINING_JOB_STATUS_SUCCEEDED).count()
    training_failed = training_jobs_query.filter(TrainingJob.status == TRAINING_JOB_STATUS_FAILED).count()
    tasks_pending = tasks_query.filter(InferenceTask.status == TASK_STATUS_PENDING).count()
    tasks_dispatched = tasks_query.filter(InferenceTask.status == TASK_STATUS_DISPATCHED).count()
    tasks_succeeded = tasks_query.filter(InferenceTask.status == TASK_STATUS_SUCCEEDED).count()
    tasks_failed = tasks_query.filter(InferenceTask.status == TASK_STATUS_FAILED).count()
    results_total = results_query.count()

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

    recent_assets_rows = assets_query.order_by(DataAsset.created_at.desc()).limit(5).all()
    recent_models_rows = models_query.order_by(ModelRecord.created_at.desc()).limit(5).all()
    recent_tasks_rows = tasks_query.order_by(InferenceTask.created_at.desc()).limit(5).all()

    audits_24h = 0
    if is_platform_user(current_user.roles):
        audits_24h = (
            db.query(AuditLog)
            .filter(AuditLog.created_at >= now - timedelta(hours=24))
            .count()
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
    }
