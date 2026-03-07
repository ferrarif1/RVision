import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.db.database import get_db
from app.db.models import InferenceResult, InferenceRun, InferenceTask
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import ASSET_UPLOAD_ROLES
from app.security.roles import RESULT_READ_ROLES
from app.security.roles import is_buyer_user
from app.services.audit_service import record_audit
from app.services.dataset_version_service import create_dataset_version_record
from app.services.result_dataset_service import DATASET_EXPORT_ALLOWED_PURPOSES
from app.services.result_dataset_service import export_tasks_to_dataset_asset

router = APIRouter(prefix="/results", tags=["results"])


class ReviewPredictionInput(BaseModel):
    label: str = Field(description="标签 / Label")
    score: float | None = Field(default=1.0, description="置信度 / Optional score")
    bbox: list[int] | None = Field(default=None, description="框坐标 / [x1, y1, x2, y2]")
    attributes: dict = Field(default_factory=dict, description="附加属性 / Optional attributes")


class ResultReviewSaveRequest(BaseModel):
    predictions: list[ReviewPredictionInput] = Field(default_factory=list, description="修订后的预测框 / Revised predictions")
    note: str | None = Field(default=None, description="修订说明 / Optional review note")


class ResultDatasetExportRequest(BaseModel):
    task_ids: list[str] = Field(default_factory=list, description="任务ID列表 / 1-n task IDs to export into a dataset asset")
    dataset_label: str = Field(default="", description="数据集标签 / Dataset label shown in asset center")
    asset_purpose: str = Field(default="training", description="用途 / training|validation|finetune")
    include_screenshots: bool = Field(default=True, description="是否打包标注截图 / Whether to include annotated preview screenshots")


def _serialize_result_row(row: InferenceResult, run: InferenceRun | None = None) -> dict:
    return {
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


def _get_task_or_404(db: Session, task_id: str, current_user: AuthUser) -> InferenceTask:
    task = db.query(InferenceTask).filter(InferenceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if is_buyer_user(current_user.roles) and task.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _get_result_or_404(db: Session, result_id: str, current_user: AuthUser) -> InferenceResult:
    result = db.query(InferenceResult).filter(InferenceResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    if is_buyer_user(current_user.roles) and result.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    return result


def _normalize_review_predictions(predictions: list[ReviewPredictionInput]) -> list[dict]:
    normalized: list[dict] = []
    for index, item in enumerate(predictions):
        label = str(item.label or "").strip()
        if not label:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Prediction #{index + 1} is missing label")
        bbox = item.bbox
        if bbox is not None:
            if len(bbox) != 4:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Prediction #{index + 1} bbox must have 4 integers")
            try:
                x1, y1, x2, y2 = [int(value) for value in bbox]
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Prediction #{index + 1} bbox must contain integers") from exc
            if min(x1, y1, x2, y2) < 0 or x2 <= x1 or y2 <= y1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Prediction #{index + 1} bbox is invalid")
            bbox = [x1, y1, x2, y2]
        normalized.append(
            {
                "label": label,
                "score": round(float(item.score if item.score is not None else 1.0), 4),
                "bbox": bbox,
                "attributes": dict(item.attributes or {}),
            }
        )
    return normalized


@router.get("")
def get_results(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*RESULT_READ_ROLES)),
):
    task = _get_task_or_404(db, task_id, current_user)

    query = db.query(InferenceResult).filter(InferenceResult.task_id == task_id)
    if is_buyer_user(current_user.roles):
        query = query.filter(InferenceResult.buyer_tenant_id == current_user.tenant_id)
    rows = query.order_by(InferenceResult.created_at.asc()).all()
    run = db.query(InferenceRun).filter(InferenceRun.task_id == task_id).order_by(InferenceRun.created_at.desc()).first()
    return [_serialize_result_row(row, run) for row in rows]


@router.get("/export")
def export_results(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*RESULT_READ_ROLES)),
):
    task = _get_task_or_404(db, task_id, current_user)

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


@router.post("/{result_id}/review")
def save_result_review(
    result_id: str,
    payload: ResultReviewSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*ASSET_UPLOAD_ROLES)),
):
    result = _get_result_or_404(db, result_id, current_user)
    normalized_predictions = _normalize_review_predictions(payload.predictions)
    result_json = dict(result.result_json or {})
    current_predictions = result_json.get("predictions") if isinstance(result_json.get("predictions"), list) else []
    if "auto_predictions" not in result_json:
        result_json["auto_predictions"] = current_predictions
    result_json["predictions"] = normalized_predictions
    result_json["matched_labels"] = sorted({str(item.get("label") or "").strip() for item in normalized_predictions if str(item.get("label") or "").strip()})
    result_json["object_count"] = len(normalized_predictions)
    result_json["review_status"] = "revised"
    result_json["manual_review"] = {
        "status": "revised",
        "prediction_count": len(normalized_predictions),
        "reviewed_by": current_user.username,
        "reviewed_at": datetime.utcnow().isoformat(),
        "note": str(payload.note or "").strip() or None,
    }
    result.result_json = result_json
    db.add(result)

    record_audit(
        db,
        action=actions.RESULT_REVIEW_SAVE,
        resource_type="result",
        resource_id=result.id,
        detail={
            "task_id": result.task_id,
            "prediction_count": len(normalized_predictions),
            "labels": result_json.get("matched_labels") or [],
            "note": result_json["manual_review"].get("note"),
        },
        request=request,
        actor=current_user,
    )
    db.commit()

    run = db.query(InferenceRun).filter(InferenceRun.task_id == result.task_id).order_by(InferenceRun.created_at.desc()).first()
    return {"result": _serialize_result_row(result, run)}


@router.post("/export-dataset")
def export_results_as_dataset(
    payload: ResultDatasetExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*ASSET_UPLOAD_ROLES)),
):
    asset_purpose = str(payload.asset_purpose or "").strip()
    if asset_purpose not in DATASET_EXPORT_ALLOWED_PURPOSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="asset_purpose must be training, validation or finetune",
        )

    dataset_label = str(payload.dataset_label or "").strip()
    if not dataset_label:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset_label is required")

    try:
        exported = export_tasks_to_dataset_asset(
            db,
            current_user=current_user,
            task_ids=payload.task_ids,
            asset_purpose=asset_purpose,
            dataset_label=dataset_label,
            include_screenshots=payload.include_screenshots,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    dataset_version = create_dataset_version_record(
        db,
        asset=exported.asset,
        dataset_label=dataset_label,
        asset_purpose=asset_purpose,
        source_type="result_export",
        summary={
            **exported.summary,
            "task_ids": payload.task_ids,
            "source": "quick_detect_result_export",
        },
        created_by=current_user.id,
    )

    record_audit(
        db,
        action=actions.RESULT_DATASET_EXPORT,
        resource_type="asset",
        resource_id=exported.asset.id,
        detail={
            "task_ids": payload.task_ids,
            "dataset_label": dataset_label,
            "asset_purpose": asset_purpose,
            "include_screenshots": payload.include_screenshots,
            "summary": exported.summary,
        },
        request=request,
        actor=current_user,
    )
    record_audit(
        db,
        action=actions.ASSET_UPLOAD,
        resource_type="asset",
        resource_id=exported.asset.id,
        detail={
            "file_name": exported.asset.file_name,
            "size": (exported.asset.meta or {}).get("size"),
            "sensitivity_level": exported.asset.sensitivity_level,
            "asset_purpose": asset_purpose,
            "asset_type": exported.asset.asset_type,
            "archive_resource_count": (exported.asset.meta or {}).get("archive_resource_count"),
            "dataset_label": dataset_label,
            "use_case": (exported.asset.meta or {}).get("use_case"),
            "intended_model_code": (exported.asset.meta or {}).get("intended_model_code"),
            "generated_from_task_ids": payload.task_ids,
        },
        request=request,
        actor=current_user,
    )
    record_audit(
        db,
        action=actions.DATASET_VERSION_CREATE,
        resource_type="dataset_version",
        resource_id=dataset_version.id,
        detail={
            "dataset_key": dataset_version.dataset_key,
            "dataset_label": dataset_version.dataset_label,
            "version": dataset_version.version,
            "asset_id": exported.asset.id,
            "asset_purpose": asset_purpose,
        },
        request=request,
        actor=current_user,
    )
    db.commit()

    return {
        "asset": {
            "id": exported.asset.id,
            "file_name": exported.asset.file_name,
            "asset_type": exported.asset.asset_type,
            "sensitivity_level": exported.asset.sensitivity_level,
            "checksum": exported.asset.checksum,
            "buyer_tenant_id": exported.asset.buyer_tenant_id,
            "meta": exported.asset.meta,
            "created_at": exported.asset.created_at,
        },
        "dataset_version": {
            "id": dataset_version.id,
            "dataset_key": dataset_version.dataset_key,
            "dataset_label": dataset_version.dataset_label,
            "version": dataset_version.version,
            "asset_id": dataset_version.asset_id,
            "asset_purpose": dataset_version.asset_purpose,
            "source_type": dataset_version.source_type,
            "summary": dataset_version.summary,
            "created_at": dataset_version.created_at,
        },
        "summary": exported.summary,
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
