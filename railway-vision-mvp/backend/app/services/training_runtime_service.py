from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.config import get_settings
from app.core.constants import TRAINING_JOB_STATUS_DISPATCHED
from app.core.constants import TRAINING_JOB_STATUS_FAILED
from app.core.constants import TRAINING_JOB_STATUS_RUNNING
from app.core.constants import TRAINING_WORKER_STATUS_ACTIVE
from app.core.constants import TRAINING_WORKER_STATUS_UNHEALTHY
from app.db.models import TrainingJob, TrainingWorker
from app.services.audit_service import record_audit


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _job_dispatch_reference_at(job: TrainingJob) -> datetime:
    summary = job.output_summary if isinstance(job.output_summary, dict) else {}
    return _parse_iso_datetime(summary.get("last_dispatched_at")) or job.created_at or datetime.utcnow()


def _set_worker_unhealthy(
    db: Session,
    worker: TrainingWorker,
    *,
    now: datetime,
    request: Request | None,
    summary: dict[str, Any],
) -> None:
    if worker.status == TRAINING_WORKER_STATUS_UNHEALTHY:
        return
    last_seen = worker.last_seen_at.isoformat() if worker.last_seen_at else None
    worker.status = TRAINING_WORKER_STATUS_UNHEALTHY
    db.add(worker)
    db.commit()
    record_audit(
        db,
        action=actions.TRAINING_WORKER_UNHEALTHY,
        resource_type="training_worker",
        resource_id=worker.id,
        detail={
            "worker_code": worker.worker_code,
            "host": worker.host,
            "last_seen_at": last_seen,
            "reconciled_at": now.isoformat(),
            "reason": "heartbeat_stale",
        },
        request=request,
        actor_role="system",
    )
    summary["unhealthy_workers"].append(worker.worker_code)


def _mark_job_failed_by_runtime(
    db: Session,
    job: TrainingJob,
    *,
    now: datetime,
    request: Request | None,
    category: str,
    reason: str,
    alert_level: str,
    recommended_action: str,
    reference_at: datetime | None,
) -> None:
    existing = job.output_summary if isinstance(job.output_summary, dict) else {}
    if job.status == TRAINING_JOB_STATUS_FAILED and existing.get("failure_category") == category:
        return
    job.status = TRAINING_JOB_STATUS_FAILED
    job.finished_at = now
    job.error_message = reason
    job.output_summary = {
        **existing,
        "stage": "failed",
        "failure_category": category,
        "retryable": True,
        "alert_level": alert_level,
        "alert_reason": reason,
        "recommended_action": recommended_action,
        "watchdog_timeout_at": now.isoformat(),
        "watchdog_reference_at": reference_at.isoformat() if reference_at else None,
        "last_control_action": "runtime_reconcile",
    }
    db.add(job)
    db.commit()
    record_audit(
        db,
        action=actions.TRAINING_JOB_TIMEOUT,
        resource_type="training_job",
        resource_id=job.id,
        detail={
            "job_code": job.job_code,
            "category": category,
            "reason": reason,
            "alert_level": alert_level,
            "recommended_action": recommended_action,
            "assigned_worker_code": job.assigned_worker_code,
            "reference_at": reference_at.isoformat() if reference_at else None,
            "reconciled_at": now.isoformat(),
        },
        request=request,
        actor_role="system",
    )


def reconcile_training_runtime_health(
    db: Session,
    *,
    request: Request | None = None,
    worker_stale_seconds: int | None = None,
    dispatch_timeout_seconds: int | None = None,
    running_timeout_seconds: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.utcnow()
    effective_worker_stale_seconds = int(worker_stale_seconds or settings.training_worker_stale_seconds)
    effective_dispatch_timeout_seconds = int(dispatch_timeout_seconds or settings.training_dispatch_timeout_seconds)
    effective_running_timeout_seconds = int(running_timeout_seconds or settings.training_running_timeout_seconds)
    worker_stale_before = now - timedelta(seconds=max(1, effective_worker_stale_seconds))
    dispatch_timeout_before = now - timedelta(seconds=max(1, effective_dispatch_timeout_seconds))
    running_timeout_before = now - timedelta(seconds=max(1, effective_running_timeout_seconds))

    summary: dict[str, Any] = {
        "reconciled_at": now.isoformat(),
        "worker_stale_seconds": effective_worker_stale_seconds,
        "dispatch_timeout_seconds": effective_dispatch_timeout_seconds,
        "running_timeout_seconds": effective_running_timeout_seconds,
        "unhealthy_workers": [],
        "failed_jobs": [],
        "counts": {
            "unhealthy_worker_count": 0,
            "timed_out_job_count": 0,
            "dispatch_timeout_count": 0,
            "running_timeout_count": 0,
            "worker_stale_job_count": 0,
        },
    }

    workers = db.query(TrainingWorker).all()
    worker_map = {row.worker_code: row for row in workers if row.worker_code}
    for worker in workers:
        if worker.status != TRAINING_WORKER_STATUS_ACTIVE:
            continue
        if worker.last_seen_at and worker.last_seen_at < worker_stale_before:
            _set_worker_unhealthy(db, worker, now=now, request=request, summary=summary)

    jobs = (
        db.query(TrainingJob)
        .filter(TrainingJob.status.in_((TRAINING_JOB_STATUS_DISPATCHED, TRAINING_JOB_STATUS_RUNNING)))
        .order_by(TrainingJob.created_at.asc())
        .all()
    )
    for job in jobs:
        assigned_worker = worker_map.get(job.assigned_worker_code or "")
        worker_is_stale = bool(assigned_worker and assigned_worker.status == TRAINING_WORKER_STATUS_UNHEALTHY)
        if job.status == TRAINING_JOB_STATUS_DISPATCHED:
            reference_at = _job_dispatch_reference_at(job)
            timed_out = reference_at < dispatch_timeout_before
            if not worker_is_stale and not timed_out:
                continue
            category = "worker_stale_dispatch" if worker_is_stale else "dispatch_timeout"
            reason = (
                "Assigned training worker heartbeat is stale before job start"
                if worker_is_stale
                else "Training job stayed DISPATCHED for too long without entering RUNNING"
            )
            _mark_job_failed_by_runtime(
                db,
                job,
                now=now,
                request=request,
                category=category,
                reason=reason,
                alert_level="CRITICAL" if worker_is_stale else "WARNING",
                recommended_action="reassign_or_retry",
                reference_at=reference_at,
            )
            summary["failed_jobs"].append(job.job_code)
            summary["counts"]["timed_out_job_count"] += 1
            if worker_is_stale:
                summary["counts"]["worker_stale_job_count"] += 1
            else:
                summary["counts"]["dispatch_timeout_count"] += 1
            continue

        reference_at = job.started_at or _job_dispatch_reference_at(job)
        timed_out = reference_at < running_timeout_before
        if not worker_is_stale and not timed_out:
            continue
        category = "worker_stale_running" if worker_is_stale else "running_timeout"
        reason = (
            "Assigned training worker heartbeat went stale while the job was RUNNING"
            if worker_is_stale
            else "Training job exceeded RUNNING timeout threshold"
        )
        _mark_job_failed_by_runtime(
            db,
            job,
            now=now,
            request=request,
            category=category,
            reason=reason,
            alert_level="CRITICAL",
            recommended_action="inspect_worker_and_retry",
            reference_at=reference_at,
        )
        summary["failed_jobs"].append(job.job_code)
        summary["counts"]["timed_out_job_count"] += 1
        if worker_is_stale:
            summary["counts"]["worker_stale_job_count"] += 1
        else:
            summary["counts"]["running_timeout_count"] += 1

    summary["counts"]["unhealthy_worker_count"] = len(summary["unhealthy_workers"])
    return summary
