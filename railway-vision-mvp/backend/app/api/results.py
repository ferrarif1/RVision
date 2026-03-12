import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.ui_errors import raise_ui_error
from app.db.database import get_db
from app.db.models import InferenceResult, InferenceRun, InferenceTask
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import ASSET_UPLOAD_ROLES
from app.security.roles import RESULT_READ_ROLES
from app.security.roles import is_buyer_user
from app.services.audit_service import record_audit
from app.services.car_number_rule_service import ensure_valid_car_number_text
from app.services.car_number_rule_service import get_active_car_number_rule
from app.services.car_number_rule_service import validate_car_number_text
from app.services.dataset_version_service import create_dataset_version_record
from app.services.result_dataset_service import DATASET_EXPORT_ALLOWED_PURPOSES
from app.services.result_dataset_service import export_tasks_to_dataset_asset

router = APIRouter(prefix="/results", tags=["results"])


class ReviewPredictionInput(BaseModel):
    label: str = Field(description="标签 / Label")
    text: str | None = Field(default=None, description="识别文本 / Optional OCR text")
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
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "task_not_found",
            "没有找到这个识别任务。",
            next_step="请确认任务编号是否正确，或回到任务中心重新选择任务。",
        )
    if is_buyer_user(current_user.roles) and task.buyer_tenant_id != current_user.tenant_id:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "task_not_found",
            "没有找到这个识别任务。",
            next_step="请确认你正在查看当前租户下的任务，或联系管理员检查任务归属。",
        )
    return task


def _get_result_or_404(db: Session, result_id: str, current_user: AuthUser) -> InferenceResult:
    result = db.query(InferenceResult).filter(InferenceResult.id == result_id).first()
    if not result:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "result_not_found",
            "没有找到这条识别结果。",
            next_step="请确认结果编号是否正确，或回到结果中心重新查询。",
        )
    if is_buyer_user(current_user.roles) and result.buyer_tenant_id != current_user.tenant_id:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "result_not_found",
            "没有找到这条识别结果。",
            next_step="请确认你正在查看当前租户下的结果，或联系管理员检查结果归属。",
        )
    return result


def _normalize_review_predictions(predictions: list[ReviewPredictionInput]) -> list[dict]:
    normalized: list[dict] = []
    for index, item in enumerate(predictions):
        label = str(item.label or "").strip()
        if not label:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "review_prediction_label_missing",
                f"第 {index + 1} 条修订结果缺少标签。",
                next_step="请先给这条修订结果补上标签，再保存复核。",
            )
        text = str(item.text or "").strip() or None
        bbox = item.bbox
        if bbox is not None:
            if len(bbox) != 4:
                raise_ui_error(
                    status.HTTP_400_BAD_REQUEST,
                    "review_prediction_bbox_length_invalid",
                    f"第 {index + 1} 条修订结果的定位框必须包含 4 个整数。",
                    next_step="请按 x1, y1, x2, y2 的格式填写定位框。",
                )
            try:
                x1, y1, x2, y2 = [int(value) for value in bbox]
            except (TypeError, ValueError) as exc:
                raise_ui_error(
                    status.HTTP_400_BAD_REQUEST,
                    "review_prediction_bbox_not_integer",
                    f"第 {index + 1} 条修订结果的定位框必须是整数。",
                    next_step="请检查定位框坐标，确保 4 个值都是整数。",
                    raw_detail=str(exc),
                )
            if min(x1, y1, x2, y2) < 0 or x2 <= x1 or y2 <= y1:
                raise_ui_error(
                    status.HTTP_400_BAD_REQUEST,
                    "review_prediction_bbox_invalid",
                    f"第 {index + 1} 条修订结果的定位框无效。",
                    next_step="请确认 x2 大于 x1、y2 大于 y1，并且坐标都不小于 0。",
                )
            bbox = [x1, y1, x2, y2]
        normalized.append(
            {
                "label": label,
                "text": text,
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
    summary = result_json.get("summary") if isinstance(result_json.get("summary"), dict) else {}
    task_type = str(result_json.get("task_type") or summary.get("task_type") or "").strip()
    if task_type == "car_number_ocr":
        for index, item in enumerate(normalized_predictions):
            if str(item.get("label") or "").strip() != "car_number":
                continue
            validation = ensure_valid_car_number_text(item.get("text"), field_name=f"predictions[{index}].text")
            item["text"] = validation["normalized_text"] or None
        best_prediction = max(
            normalized_predictions,
            key=lambda item: float(item.get("score") if item.get("score") is not None else 0),
            default=None,
        )
        best_text = str((best_prediction or {}).get("text") or "").strip() or None
        validation = validate_car_number_text(best_text)
        result_json["summary"] = {
            **summary,
            "task_type": "car_number_ocr",
            "car_number": validation["normalized_text"] or None,
            "confidence": (best_prediction or {}).get("score"),
            "bbox": (best_prediction or {}).get("bbox"),
            "car_number_validation": validation,
            "car_number_rule": get_active_car_number_rule(),
        }
        result_json["car_number"] = validation["normalized_text"] or None
        result_json["car_number_validation"] = validation
        result_json["car_number_rule"] = get_active_car_number_rule()
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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "result_dataset_purpose_invalid",
            "数据用途只能是训练、验证或微调。",
            next_step="请把数据用途改成 training、validation 或 finetune 之一。",
        )

    dataset_label = str(payload.dataset_label or "").strip()
    if not dataset_label:
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "result_dataset_label_required",
            "导出训练数据前需要填写数据集标签。",
            next_step="请先填写一个容易识别的数据集标签，再继续导出。",
        )

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
        raise_ui_error(
            status.HTTP_400_BAD_REQUEST,
            "result_dataset_export_invalid",
            "这批结果暂时不能整理成训练数据。",
            next_step="请检查任务选择、数据用途和当前结果状态后重试。",
            raw_detail=str(exc),
        )
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
    result = _get_result_or_404(db, result_id, current_user)
    if not result.screenshot_uri:
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "result_screenshot_not_found",
            "这条结果还没有可查看的截图。",
            next_step="请先重新执行任务或查看其他带截图的结果。",
        )
    if not os.path.exists(result.screenshot_uri):
        raise_ui_error(
            status.HTTP_404_NOT_FOUND,
            "result_screenshot_file_missing",
            "结果截图文件已不存在。",
            next_step="请重新执行一次任务生成截图，或联系管理员检查资源文件。",
        )

    return FileResponse(result.screenshot_uri, media_type="image/jpeg", filename=f"{result_id}.jpg")
