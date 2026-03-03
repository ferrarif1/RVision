import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.audit import actions
from app.db.database import get_db
from app.db.models import InferenceResult, InferenceRun, InferenceTask
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import RESULT_READ_ROLES
from app.security.roles import is_buyer_user
from app.services.audit_service import record_audit

router = APIRouter(prefix="/results", tags=["results"])


@router.get("")
def get_results(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*RESULT_READ_ROLES)),
):
    task = db.query(InferenceTask).filter(InferenceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if is_buyer_user(current_user.roles) and task.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    query = db.query(InferenceResult).filter(InferenceResult.task_id == task_id)
    if is_buyer_user(current_user.roles):
        query = query.filter(InferenceResult.buyer_tenant_id == current_user.tenant_id)
    rows = query.order_by(InferenceResult.created_at.asc()).all()
    run = db.query(InferenceRun).filter(InferenceRun.task_id == task_id).order_by(InferenceRun.created_at.desc()).first()
    return [
        {
            "id": row.id,
            "task_id": row.task_id,
            "model_id": row.model_id,
            "model_hash": row.model_hash,
            "alert_level": row.alert_level,
            "result_json": row.result_json,
            "screenshot_uri": row.screenshot_uri,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at,
            "run": {
                "job_id": run.job_id,
                "pipeline_id": run.pipeline_id,
                "pipeline_version": run.pipeline_version,
                "threshold_version": run.threshold_version,
                "audit_hash": run.audit_hash,
            }
            if run
            else None,
        }
        for row in rows
    ]


@router.get("/export")
def export_results(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*RESULT_READ_ROLES)),
):
    task = db.query(InferenceTask).filter(InferenceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if is_buyer_user(current_user.roles) and task.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    query = db.query(InferenceResult).filter(InferenceResult.task_id == task_id)
    if is_buyer_user(current_user.roles):
        query = query.filter(InferenceResult.buyer_tenant_id == current_user.tenant_id)
    rows = query.order_by(InferenceResult.created_at.asc()).all()
    run = db.query(InferenceRun).filter(InferenceRun.task_id == task_id).order_by(InferenceRun.created_at.desc()).first()
    payload = [
        {
            "id": row.id,
            "task_id": row.task_id,
            "model_id": row.model_id,
            "model_hash": row.model_hash,
            "alert_level": row.alert_level,
            "result_json": row.result_json,
            "screenshot_uri": row.screenshot_uri,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]

    record_audit(
        db,
        action=actions.RESULT_EXPORT,
        resource_type="result",
        resource_id=task_id,
        detail={"count": len(payload)},
        request=request,
        actor=current_user,
    )

    return {
        "task_id": task_id,
        "count": len(payload),
        "items": payload,
        "run": {
            "job_id": run.job_id,
            "pipeline_id": run.pipeline_id,
            "pipeline_version": run.pipeline_version,
            "threshold_version": run.threshold_version,
            "input_hash": run.input_hash,
            "models_versions": run.models_versions,
            "timings": run.timings,
            "result_summary": run.result_summary,
            "audit_hash": run.audit_hash,
        }
        if run
        else None,
    }


@router.get("/{result_id}/screenshot")
def get_result_screenshot(
    result_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*RESULT_READ_ROLES)),
):
    result = db.query(InferenceResult).filter(InferenceResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    if is_buyer_user(current_user.roles) and result.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    if not result.screenshot_uri:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")
    if not os.path.exists(result.screenshot_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot file missing")

    return FileResponse(result.screenshot_uri, media_type="image/jpeg", filename=f"{result_id}.jpg")
