import hashlib
import json
import mimetypes
import os
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import DataAsset, DatasetVersion, Tenant
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import ASSET_UPLOAD_ROLES, MODEL_READ_ROLES, is_buyer_user, is_platform_user, is_supplier_user
from app.services.audit_service import record_audit
from app.services.dataset_version_service import create_dataset_version_record

router = APIRouter(prefix="/assets", tags=["assets"])

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov"}
ARCHIVE_EXTENSIONS = {".zip"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
ALLOWED_EXTENSIONS = MEDIA_EXTENSIONS | ARCHIVE_EXTENSIONS
ASSET_PURPOSES = {"training", "finetune", "validation", "inference"}
ARCHIVE_ALLOWED_PURPOSES = {"training", "finetune", "validation"}
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_FILE_NAME_LENGTH = 255
ARCHIVE_PREVIEW_LIMIT = 20
DATASET_COMPARE_SAMPLE_LIMIT = 8
DATASET_COMPARE_SCOPES = {"all", "added", "removed", "changed"}


class DatasetVersionRecommendRequest(BaseModel):
    asset_purpose: str | None = Field(default=None, description="推荐用途 / Optional recommendation target purpose")
    note: str | None = Field(default=None, description="推荐说明 / Optional recommendation note")


class DatasetVersionRollbackRequest(BaseModel):
    asset_purpose: str | None = Field(default=None, description="回滚后的用途 / Optional asset purpose for the rolled-back version")
    note: str | None = Field(default=None, description="回滚说明 / Optional rollback note")


def _safe_original_file_name(file_name: str | None) -> tuple[str, str]:
    cleaned = os.path.basename(str(file_name or "").strip())
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing file name")
    cleaned = cleaned[:MAX_FILE_NAME_LENGTH]
    ext = os.path.splitext(cleaned.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")
    return cleaned, ext


def _resolve_buyer_tenant_id(
    db: Session,
    current_user: AuthUser,
    buyer_tenant_code: str,
) -> str | None:
    if is_buyer_user(current_user.roles):
        return current_user.tenant_id
    if is_platform_user(current_user.roles) and buyer_tenant_code:
        tenant = (
            db.query(Tenant)
            .filter(Tenant.tenant_code == buyer_tenant_code, Tenant.tenant_type == "BUYER", Tenant.status == "ACTIVE")
            .first()
        )
        if not tenant:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid buyer_tenant_code")
        return tenant.id
    return None


def _asset_type_from_extension(ext: str) -> str:
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")


def _validate_archive_policy(ext: str, asset_purpose: str) -> None:
    if ext in ARCHIVE_EXTENSIONS and asset_purpose not in ARCHIVE_ALLOWED_PURPOSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZIP dataset asset is only allowed for training, finetune or validation purpose",
        )


def _normalize_archive_member(name: str) -> PurePosixPath:
    normalized = str(name or "").replace("\\", "/").strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archive contains empty entry name")
    member = PurePosixPath(normalized)
    if member.is_absolute() or any(part in {"", ".", ".."} for part in member.parts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archive contains unsafe entry path")
    return member


def _inspect_archive_bundle(
    storage_uri: str,
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
) -> dict:
    try:
        with zipfile.ZipFile(storage_uri) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ZIP archive") from exc

    if not infos:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ZIP archive is empty")
    if len(infos) > max_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ZIP archive has too many entries, max allowed is {max_entries}",
        )

    file_count = 0
    directory_count = 0
    ignored_entry_count = 0
    image_count = 0
    video_count = 0
    max_depth = 0
    total_uncompressed_bytes = 0
    preview_members: list[str] = []

    # 只接受 ZIP 中的图片/视频资源；其他元文件允许存在但不会被计入可训练样本。
    # Only image/video members are counted as usable dataset resources; other files are ignored.
    for info in infos:
        member = _normalize_archive_member(info.filename)
        if info.is_dir() or str(info.filename).endswith("/"):
            directory_count += 1
            max_depth = max(max_depth, len(member.parts) - 1)
            continue

        file_count += 1
        max_depth = max(max_depth, len(member.parts) - 1)
        total_uncompressed_bytes += max(info.file_size, 0)
        if total_uncompressed_bytes > max_uncompressed_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ZIP archive is too large after decompression, max allowed is {max_uncompressed_bytes} bytes",
            )

        ext = os.path.splitext(member.name.lower())[1]
        if ext in IMAGE_EXTENSIONS:
            image_count += 1
            if len(preview_members) < ARCHIVE_PREVIEW_LIMIT:
                preview_members.append(str(member))
        elif ext in VIDEO_EXTENSIONS:
            video_count += 1
            if len(preview_members) < ARCHIVE_PREVIEW_LIMIT:
                preview_members.append(str(member))
        else:
            ignored_entry_count += 1

    resource_count = image_count + video_count
    if resource_count <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZIP archive must contain at least one supported image or video file",
        )

    return {
        "archive_kind": "zip_dataset",
        "archive_entry_count": len(infos),
        "archive_file_count": file_count,
        "archive_directory_count": directory_count,
        "archive_resource_count": resource_count,
        "archive_image_count": image_count,
        "archive_video_count": video_count,
        "archive_ignored_entry_count": ignored_entry_count,
        "archive_max_depth": max_depth,
        "archive_preview_members": preview_members,
        "archive_uncompressed_bytes": total_uncompressed_bytes,
    }


def _persist_upload_stream(file: UploadFile, target_dir: str, asset_id: str, ext: str, max_bytes: int) -> tuple[str, str, int]:
    temp_uri = os.path.join(target_dir, f".upload-{asset_id}{ext}")
    storage_uri = os.path.join(target_dir, f"{asset_id}{ext}")
    checksum = hashlib.sha256()
    size = 0
    try:
        with open(temp_uri, "wb") as output:
            while True:
                chunk = file.file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File too large, max allowed is {max_bytes} bytes",
                    )
                checksum.update(chunk)
                output.write(chunk)
        if size <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file is not allowed")
        os.replace(temp_uri, storage_uri)
        return storage_uri, checksum.hexdigest(), size
    except Exception:
        if os.path.exists(temp_uri):
            os.remove(temp_uri)
        raise
    finally:
        file.file.close()


def _same_optional_text(left: str | None, right: str | None) -> bool:
    return (left or "").strip() == (right or "").strip()


def _find_reusable_asset(
    db: Session,
    *,
    file_name: str,
    asset_type: str,
    sensitivity_level: str,
    checksum: str,
    buyer_tenant_id: str | None,
    source_uri: str | None,
    meta: dict,
) -> DataAsset | None:
    query = db.query(DataAsset).filter(
        DataAsset.checksum == checksum,
        DataAsset.file_name == file_name,
        DataAsset.asset_type == asset_type,
        DataAsset.sensitivity_level == sensitivity_level,
    )
    if buyer_tenant_id:
        query = query.filter(DataAsset.buyer_tenant_id == buyer_tenant_id)
    else:
        query = query.filter(DataAsset.buyer_tenant_id.is_(None))

    for row in query.order_by(DataAsset.created_at.desc()).limit(10).all():
        row_meta = row.meta if isinstance(row.meta, dict) else {}
        if row_meta == meta and _same_optional_text(row.source_uri, source_uri):
            return row
    return None


def _serialize_asset(asset: DataAsset) -> dict:
    return {
        "id": asset.id,
        "file_name": asset.file_name,
        "asset_type": asset.asset_type,
        "sensitivity_level": asset.sensitivity_level,
        "buyer_tenant_id": asset.buyer_tenant_id,
        "checksum": asset.checksum,
        "meta": asset.meta,
    }


def _get_visible_asset_or_404(db: Session, asset_id: str, current_user: AuthUser) -> DataAsset:
    asset = db.query(DataAsset).filter(DataAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if is_supplier_user(current_user.roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if is_buyer_user(current_user.roles) and asset.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


def _get_visible_dataset_version_or_404(db: Session, version_id: str, current_user: AuthUser) -> DatasetVersion:
    row = db.query(DatasetVersion).filter(DatasetVersion.id == version_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found")
    if is_supplier_user(current_user.roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found")
    if is_buyer_user(current_user.roles) and row.buyer_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found")
    return row


def _serialize_dataset_version(row: DatasetVersion, asset: DataAsset | None = None, buyer: Tenant | None = None) -> dict:
    summary = row.summary or {}
    return {
        "id": row.id,
        "dataset_key": row.dataset_key,
        "dataset_label": row.dataset_label,
        "version": row.version,
        "asset_id": row.asset_id,
        "asset_purpose": row.asset_purpose,
        "buyer_tenant_id": row.buyer_tenant_id,
        "buyer_tenant_code": buyer.tenant_code if buyer else None,
        "buyer_tenant_name": buyer.name if buyer else None,
        "source_type": row.source_type,
        "summary": summary,
        "recommended": bool(summary.get("recommended")),
        "asset": {
            "id": asset.id,
            "file_name": asset.file_name,
            "asset_type": asset.asset_type,
            "meta": asset.meta if isinstance(asset.meta, dict) else {},
            "created_at": asset.created_at,
        }
        if asset
        else None,
        "created_at": row.created_at,
    }


def _dataset_sample_summary(record: dict[str, Any]) -> dict[str, Any]:
    matched_labels = sorted({str(item).strip() for item in (record.get("matched_labels") or []) if str(item).strip()})
    return {
        "sample_id": record.get("sample_id") or record.get("task_id") or record.get("asset_id"),
        "task_id": record.get("task_id"),
        "asset_id": record.get("asset_id"),
        "source_file_name": record.get("source_file_name"),
        "object_prompt": record.get("object_prompt"),
        "object_count": int(record.get("object_count") or 0),
        "matched_labels": matched_labels,
        "review_status": record.get("review_status"),
        "preview_file": record.get("preview_file"),
    }


def _dataset_sample_signature(summary: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(summary.get("matched_labels") or []),
        summary.get("review_status"),
        int(summary.get("object_count") or 0),
        summary.get("object_prompt"),
    )


def _matches_dataset_sample_filters(
    summary: dict[str, Any],
    *,
    label: str | None,
    review_status: str | None,
    sample_query: str | None,
) -> bool:
    if label and label not in (summary.get("matched_labels") or []):
        return False
    if review_status and str(summary.get("review_status") or "").strip() != review_status:
        return False
    if sample_query:
        haystacks = [
            str(summary.get("sample_id") or "").lower(),
            str(summary.get("source_file_name") or "").lower(),
            str(summary.get("object_prompt") or "").lower(),
        ]
        if not any(sample_query in item for item in haystacks):
            return False
    return True


def _copy_file_with_checksum(source_path: str, target_path: str) -> tuple[str, int]:
    checksum = hashlib.sha256()
    size = 0
    with open(source_path, "rb") as src, open(target_path, "wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            checksum.update(chunk)
            size += len(chunk)
            dst.write(chunk)
    return checksum.hexdigest(), size


def _load_dataset_archive_payload(asset: DataAsset, *, preview_limit: int | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if asset.asset_type != "archive":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset preview is only available for archive assets")
    if not os.path.exists(asset.storage_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset archive file missing")

    manifest: dict[str, Any] = {}
    samples: list[dict[str, Any]] = []
    sample_map: dict[str, dict[str, Any]] = {}
    try:
        with zipfile.ZipFile(asset.storage_uri) as zf:
            if "manifest.json" in zf.namelist():
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            if "annotations/records.jsonl" in zf.namelist():
                lines = zf.read("annotations/records.jsonl").decode("utf-8").splitlines()
                for line in lines:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    summary = _dataset_sample_summary(record)
                    sample_id = str(summary.get("sample_id") or "").strip()
                    if not sample_id:
                        continue
                    sample_map[sample_id] = summary
                    if preview_limit is None or len(samples) < preview_limit:
                        samples.append(summary)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dataset archive") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset archive metadata is malformed") from exc
    return manifest, samples, sample_map


@router.get("")
def list_assets(
    q: str | None = Query(default=None, description="关键词搜索 / Keyword search across file and metadata"),
    asset_type: str | None = Query(default=None, description="资产类型 / Asset type: image|video|archive"),
    asset_purpose: str | None = Query(default=None, description="资产用途 / Asset purpose: training|finetune|validation|inference"),
    sensitivity_level: str | None = Query(default=None, description="敏感级别 / Sensitivity level: L1|L2|L3"),
    buyer_tenant_code: str | None = Query(default=None, description="买家租户编码 / Buyer tenant code (platform role only)"),
    limit: int = Query(default=100, ge=1, le=500, description="返回条数上限 / Max number of returned rows"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    if is_supplier_user(current_user.roles):
        # 安全边界：供应商角色不允许直接遍历买家原始资产。
        # Security boundary: supplier cannot enumerate buyer raw assets.
        return []

    query = db.query(DataAsset).order_by(DataAsset.created_at.desc())
    if is_buyer_user(current_user.roles):
        query = query.filter(DataAsset.buyer_tenant_id == current_user.tenant_id)
    elif buyer_tenant_code and is_platform_user(current_user.roles):
        buyer_tenant = (
            db.query(Tenant)
            .filter(Tenant.tenant_code == buyer_tenant_code, Tenant.tenant_type == "BUYER", Tenant.status == "ACTIVE")
            .first()
        )
        if not buyer_tenant:
            return []
        query = query.filter(DataAsset.buyer_tenant_id == buyer_tenant.id)

    if asset_type:
        query = query.filter(DataAsset.asset_type == asset_type)
    if sensitivity_level:
        query = query.filter(DataAsset.sensitivity_level == sensitivity_level)

    rows = query.limit(limit).all()
    tenant_ids = {row.buyer_tenant_id for row in rows if row.buyer_tenant_id}
    tenant_map = {
        row.id: row
        for row in db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).all()
    }

    keyword = (q or "").strip().lower()
    payload = []
    for row in rows:
        meta = row.meta if isinstance(row.meta, dict) else {}
        row_asset_purpose = str(meta.get("asset_purpose") or "")
        if asset_purpose and row_asset_purpose != asset_purpose:
            continue
        if keyword:
            haystacks = [
                (row.file_name or "").lower(),
                (row.asset_type or "").lower(),
                (row.sensitivity_level or "").lower(),
                row_asset_purpose.lower(),
                str(meta.get("dataset_label") or "").lower(),
                str(meta.get("use_case") or "").lower(),
                str(meta.get("intended_model_code") or "").lower(),
                str(meta.get("archive_kind") or "").lower(),
                str(meta.get("archive_preview_members") or "").lower(),
            ]
            if not any(keyword in item for item in haystacks):
                continue
        buyer = tenant_map.get(row.buyer_tenant_id)
        payload.append(
            {
                "id": row.id,
                "file_name": row.file_name,
                "asset_type": row.asset_type,
                "sensitivity_level": row.sensitivity_level,
                "checksum": row.checksum,
                "buyer_tenant_id": row.buyer_tenant_id,
                "buyer_tenant_code": buyer.tenant_code if buyer else None,
                "buyer_tenant_name": buyer.name if buyer else None,
                "meta": meta,
                "created_at": row.created_at,
            }
        )
    return payload


@router.get("/dataset-versions")
def list_dataset_versions(
    q: str | None = Query(default=None, description="关键词搜索 / Keyword search in dataset label or version"),
    asset_purpose: str | None = Query(default=None, description="资产用途 / training|validation|finetune"),
    buyer_tenant_code: str | None = Query(default=None, description="买家租户编码 / Buyer tenant code (platform role only)"),
    limit: int = Query(default=100, ge=1, le=500, description="返回条数上限 / Max number of returned rows"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    if is_supplier_user(current_user.roles):
        return []

    query = db.query(DatasetVersion).order_by(DatasetVersion.created_at.desc())
    if is_buyer_user(current_user.roles):
        query = query.filter(DatasetVersion.buyer_tenant_id == current_user.tenant_id)
    elif buyer_tenant_code and is_platform_user(current_user.roles):
        buyer_tenant = (
            db.query(Tenant)
            .filter(Tenant.tenant_code == buyer_tenant_code, Tenant.tenant_type == "BUYER", Tenant.status == "ACTIVE")
            .first()
        )
        if not buyer_tenant:
            return []
        query = query.filter(DatasetVersion.buyer_tenant_id == buyer_tenant.id)

    if asset_purpose:
        query = query.filter(DatasetVersion.asset_purpose == asset_purpose)

    rows = query.limit(limit).all()
    asset_ids = [row.asset_id for row in rows if row.asset_id]
    asset_map = {row.id: row for row in db.query(DataAsset).filter(DataAsset.id.in_(asset_ids)).all()}
    tenant_ids = {row.buyer_tenant_id for row in rows if row.buyer_tenant_id}
    tenant_map = {row.id: row for row in db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).all()}
    keyword = str(q or "").strip().lower()
    payload = []
    for row in rows:
        asset = asset_map.get(row.asset_id)
        buyer = tenant_map.get(row.buyer_tenant_id)
        if keyword:
            haystacks = [
                str(row.dataset_key or "").lower(),
                str(row.dataset_label or "").lower(),
                str(row.version or "").lower(),
                str(row.asset_purpose or "").lower(),
                str((row.summary or {}).get("label_vocab") or "").lower(),
            ]
            if not any(keyword in item for item in haystacks):
                continue
        payload.append(_serialize_dataset_version(row, asset=asset, buyer=buyer))
    return payload


@router.get("/dataset-versions/compare")
def compare_dataset_versions(
    left_id: str = Query(..., description="左侧版本ID / Left dataset version id"),
    right_id: str = Query(..., description="右侧版本ID / Right dataset version id"),
    sample_limit: int = Query(default=DATASET_COMPARE_SAMPLE_LIMIT, ge=1, le=20, description="样本差异返回条数 / Sample diff rows"),
    change_scope: str = Query(default="all", description="差异范围 / all|added|removed|changed"),
    label: str | None = Query(default=None, description="按标签筛选 / Filter diff rows by label"),
    review_status: str | None = Query(default=None, description="按 review 状态筛选 / Filter by review status"),
    changed_field: str | None = Query(default=None, description="按变更字段筛选 / Filter changed rows by changed field"),
    q: str | None = Query(default=None, description="样本关键词 / Sample keyword in id, file name or prompt"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    normalized_scope = str(change_scope or "all").strip().lower()
    if normalized_scope not in DATASET_COMPARE_SCOPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid change_scope")
    normalized_label = str(label or "").strip()
    normalized_review_status = str(review_status or "").strip()
    normalized_changed_field = str(changed_field or "").strip()
    sample_query = str(q or "").strip().lower()
    left = _get_visible_dataset_version_or_404(db, left_id, current_user)
    right = _get_visible_dataset_version_or_404(db, right_id, current_user)
    left_asset = db.query(DataAsset).filter(DataAsset.id == left.asset_id).first() if left.asset_id else None
    right_asset = db.query(DataAsset).filter(DataAsset.id == right.asset_id).first() if right.asset_id else None
    left_summary = left.summary or {}
    right_summary = right.summary or {}
    left_labels = set(left_summary.get("label_vocab") or [])
    right_labels = set(right_summary.get("label_vocab") or [])
    left_manifest, _, left_samples = _load_dataset_archive_payload(left_asset, preview_limit=None) if left_asset else ({}, [], {})
    right_manifest, _, right_samples = _load_dataset_archive_payload(right_asset, preview_limit=None) if right_asset else ({}, [], {})
    left_sample_ids = set(left_samples.keys())
    right_sample_ids = set(right_samples.keys())
    added_ids = sorted(right_sample_ids - left_sample_ids)
    removed_ids = sorted(left_sample_ids - right_sample_ids)
    changed_ids = sorted(
        sample_id
        for sample_id in (left_sample_ids & right_sample_ids)
        if _dataset_sample_signature(left_samples[sample_id]) != _dataset_sample_signature(right_samples[sample_id])
    )

    added_samples = [right_samples[sample_id] for sample_id in added_ids]
    if normalized_label or normalized_review_status or sample_query:
        added_samples = [
            row
            for row in added_samples
            if _matches_dataset_sample_filters(
                row,
                label=normalized_label or None,
                review_status=normalized_review_status or None,
                sample_query=sample_query or None,
            )
        ]

    removed_samples = [left_samples[sample_id] for sample_id in removed_ids]
    if normalized_label or normalized_review_status or sample_query:
        removed_samples = [
            row
            for row in removed_samples
            if _matches_dataset_sample_filters(
                row,
                label=normalized_label or None,
                review_status=normalized_review_status or None,
                sample_query=sample_query or None,
            )
        ]

    changed_samples = []
    for sample_id in changed_ids:
        left_row = left_samples[sample_id]
        right_row = right_samples[sample_id]
        change_fields = [
            field
            for field in ("matched_labels", "review_status", "object_count", "object_prompt")
            if left_row.get(field) != right_row.get(field)
        ]
        if normalized_changed_field and normalized_changed_field not in change_fields:
            continue
        if normalized_label or normalized_review_status or sample_query:
            if not (
                _matches_dataset_sample_filters(
                    left_row,
                    label=normalized_label or None,
                    review_status=normalized_review_status or None,
                    sample_query=sample_query or None,
                )
                or _matches_dataset_sample_filters(
                    right_row,
                    label=normalized_label or None,
                    review_status=normalized_review_status or None,
                    sample_query=sample_query or None,
                )
            ):
                continue
        changed_samples.append(
            {
                "sample_id": sample_id,
                "source_file_name": right_row.get("source_file_name") or left_row.get("source_file_name"),
                "change_fields": change_fields,
                "left": left_row,
                "right": right_row,
            }
        )

    if normalized_scope == "added":
        removed_samples = []
        changed_samples = []
    elif normalized_scope == "removed":
        added_samples = []
        changed_samples = []
    elif normalized_scope == "changed":
        added_samples = []
        removed_samples = []

    return {
        "left": _serialize_dataset_version(left, asset=left_asset),
        "right": _serialize_dataset_version(right, asset=right_asset),
        "diff": {
            "same_dataset_key": left.dataset_key == right.dataset_key,
            "task_count_delta": int(right_summary.get("task_count") or 0) - int(left_summary.get("task_count") or 0),
            "resource_count_delta": int(right_summary.get("resource_count") or 0) - int(left_summary.get("resource_count") or 0),
            "reviewed_task_count_delta": int(right_summary.get("reviewed_task_count") or 0) - int(left_summary.get("reviewed_task_count") or 0),
            "labels_added": sorted(right_labels - left_labels),
            "labels_removed": sorted(left_labels - right_labels),
            "sample_added_count": len(added_ids),
            "sample_removed_count": len(removed_ids),
            "sample_changed_count": len(changed_ids),
            "sample_task_count_delta": int(right_manifest.get("task_count") or len(right_sample_ids)) - int(left_manifest.get("task_count") or len(left_sample_ids)),
            "filtered_sample_count": len(added_samples) + len(removed_samples) + len(changed_samples),
            "applied_filters": {
                "change_scope": normalized_scope,
                "label": normalized_label or None,
                "review_status": normalized_review_status or None,
                "changed_field": normalized_changed_field or None,
                "q": sample_query or None,
            },
            "added_samples": added_samples[:sample_limit],
            "removed_samples": removed_samples[:sample_limit],
            "changed_samples": changed_samples[:sample_limit],
        },
    }


@router.post("/dataset-versions/{version_id}/recommend")
def recommend_dataset_version(
    version_id: str,
    payload: DatasetVersionRecommendRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*ASSET_UPLOAD_ROLES)),
):
    row = _get_visible_dataset_version_or_404(db, version_id, current_user)
    asset = _get_visible_asset_or_404(db, row.asset_id, current_user)
    summary = dict(row.summary or {})
    note = str(payload.note or "").strip() or None
    target_purpose = str(payload.asset_purpose or row.asset_purpose or "").strip() or row.asset_purpose
    summary.update(
        {
            "recommended": True,
            "recommended_for": target_purpose,
            "recommended_at": datetime.utcnow().isoformat(),
            "recommended_by": current_user.username,
            "recommended_note": note,
        }
    )
    row.summary = summary
    if target_purpose:
        row.asset_purpose = target_purpose
    db.add(row)

    asset_meta = dict(asset.meta or {})
    asset_meta.update(
        {
            "dataset_recommended": True,
            "dataset_recommended_for": target_purpose,
            "dataset_recommended_by": current_user.username,
            "dataset_recommended_note": note,
        }
    )
    asset.meta = asset_meta
    db.add(asset)

    record_audit(
        db,
        action=actions.DATASET_VERSION_RECOMMEND,
        resource_type="dataset_version",
        resource_id=row.id,
        detail={
            "dataset_key": row.dataset_key,
            "dataset_label": row.dataset_label,
            "version": row.version,
            "asset_id": row.asset_id,
            "asset_purpose": row.asset_purpose,
            "recommended_for": target_purpose,
            "note": note,
        },
        request=request,
        actor=current_user,
    )
    db.commit()
    db.refresh(row)
    db.refresh(asset)
    buyer = db.query(Tenant).filter(Tenant.id == row.buyer_tenant_id).first() if row.buyer_tenant_id else None
    return {"dataset_version": _serialize_dataset_version(row, asset=asset, buyer=buyer)}


@router.post("/dataset-versions/{version_id}/rollback")
def rollback_dataset_version(
    version_id: str,
    payload: DatasetVersionRollbackRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*ASSET_UPLOAD_ROLES)),
):
    row = _get_visible_dataset_version_or_404(db, version_id, current_user)
    asset = _get_visible_asset_or_404(db, row.asset_id, current_user)
    if asset.asset_type != "archive":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only archive dataset versions can be rolled back")
    if not os.path.exists(asset.storage_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset archive file missing")

    settings = get_settings()
    rollback_dir = os.path.join(settings.asset_repo_path, "generated_datasets")
    os.makedirs(rollback_dir, exist_ok=True)

    new_asset_id = str(uuid.uuid4())
    ext = os.path.splitext(asset.file_name or "")[1] or ".zip"
    rollback_file_name = f"{(row.dataset_label or 'dataset').replace(' ', '-')}_rollback{ext}"
    rollback_storage_uri = os.path.join(rollback_dir, f"{new_asset_id}{ext}")
    checksum, file_size = _copy_file_with_checksum(asset.storage_uri, rollback_storage_uri)

    note = str(payload.note or "").strip() or None
    target_purpose = str(payload.asset_purpose or row.asset_purpose or "").strip() or row.asset_purpose
    source_meta = dict(asset.meta or {})
    for key in (
        "dataset_version",
        "dataset_version_id",
        "dataset_recommended",
        "dataset_recommended_for",
        "dataset_recommended_by",
        "dataset_recommended_note",
    ):
        source_meta.pop(key, None)
    source_meta.update(
        {
            "size": file_size,
            "asset_purpose": target_purpose,
            "dataset_label": row.dataset_label,
            "dataset_rollback_from_version_id": row.id,
            "dataset_rollback_from_version": row.version,
            "dataset_rollback_note": note,
        }
    )
    rollback_asset = DataAsset(
        id=new_asset_id,
        file_name=rollback_file_name,
        asset_type="archive",
        storage_uri=rollback_storage_uri,
        source_uri=f"vistral://assets/dataset-rollback/{row.id}",
        sensitivity_level=asset.sensitivity_level,
        checksum=checksum,
        buyer_tenant_id=asset.buyer_tenant_id,
        meta=source_meta,
        uploaded_by=current_user.id,
    )
    db.add(rollback_asset)
    db.flush()

    rollback_summary = {
        **(row.summary or {}),
        "recommended": False,
        "recommended_for": None,
        "recommended_at": None,
        "recommended_by": None,
        "recommended_note": None,
        "rollback_from_version_id": row.id,
        "rollback_from_version": row.version,
        "rollback_at": datetime.utcnow().isoformat(),
        "rollback_by": current_user.username,
        "rollback_note": note,
    }
    dataset_version = create_dataset_version_record(
        db,
        asset=rollback_asset,
        dataset_label=row.dataset_label,
        dataset_key=row.dataset_key,
        asset_purpose=target_purpose,
        source_type="rollback",
        summary=rollback_summary,
        created_by=current_user.id,
    )

    record_audit(
        db,
        action=actions.DATASET_VERSION_ROLLBACK,
        resource_type="dataset_version",
        resource_id=dataset_version.id,
        detail={
            "dataset_key": row.dataset_key,
            "dataset_label": row.dataset_label,
            "rollback_from_version_id": row.id,
            "rollback_from_version": row.version,
            "rollback_to_version_id": dataset_version.id,
            "rollback_to_version": dataset_version.version,
            "asset_id": rollback_asset.id,
            "asset_purpose": target_purpose,
            "note": note,
        },
        request=request,
        actor=current_user,
    )
    db.commit()
    db.refresh(dataset_version)
    db.refresh(rollback_asset)
    buyer = db.query(Tenant).filter(Tenant.id == dataset_version.buyer_tenant_id).first() if dataset_version.buyer_tenant_id else None
    return {
        "dataset_version": _serialize_dataset_version(dataset_version, asset=rollback_asset, buyer=buyer),
        "rolled_back_from": _serialize_dataset_version(row, asset=asset, buyer=buyer),
    }


@router.get("/dataset-versions/{version_id}/preview")
def preview_dataset_version(
    version_id: str,
    sample_limit: int = Query(default=6, ge=1, le=20, description="样本预览条数 / Sample preview rows"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    row = _get_visible_dataset_version_or_404(db, version_id, current_user)
    asset = _get_visible_asset_or_404(db, row.asset_id, current_user)
    if asset.asset_type != "archive":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset preview is only available for archive assets")
    if not os.path.exists(asset.storage_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset archive file missing")

    manifest: dict = {}
    samples: list[dict] = []
    try:
        with zipfile.ZipFile(asset.storage_uri) as zf:
            if "manifest.json" in zf.namelist():
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            if "annotations/records.jsonl" in zf.namelist():
                lines = zf.read("annotations/records.jsonl").decode("utf-8").splitlines()
                for line in lines[:sample_limit]:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    samples.append(
                        {
                            "sample_id": record.get("sample_id"),
                            "task_id": record.get("task_id"),
                            "asset_id": record.get("asset_id"),
                            "asset_type": record.get("asset_type"),
                            "source_file": record.get("source_file"),
                            "source_file_name": record.get("source_file_name"),
                            "object_prompt": record.get("object_prompt"),
                            "object_count": record.get("object_count"),
                            "matched_labels": record.get("matched_labels") or [],
                            "review_status": record.get("review_status"),
                            "preview_file": record.get("preview_file"),
                        }
                    )
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dataset archive") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset archive metadata is malformed") from exc

    buyer = db.query(Tenant).filter(Tenant.id == row.buyer_tenant_id).first() if row.buyer_tenant_id else None
    return {
        "dataset_version": _serialize_dataset_version(row, asset=asset, buyer=buyer),
        "manifest": manifest,
        "samples": samples,
    }


@router.get("/dataset-versions/{version_id}/preview-file")
def get_dataset_version_preview_file(
    version_id: str,
    member: str = Query(..., description="压缩包成员路径 / Archive member path"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    row = _get_visible_dataset_version_or_404(db, version_id, current_user)
    asset = _get_visible_asset_or_404(db, row.asset_id, current_user)
    if asset.asset_type != "archive":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset preview file is only available for archive assets")
    if not os.path.exists(asset.storage_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset archive file missing")

    normalized = str(_normalize_archive_member(member))
    if not normalized.startswith(("previews/", "assets/")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported dataset preview member")

    try:
        with zipfile.ZipFile(asset.storage_uri) as zf:
            if normalized not in zf.namelist():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset preview member missing")
            payload = zf.read(normalized)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dataset archive") from exc

    media_type = mimetypes.guess_type(normalized)[0] or "application/octet-stream"
    return Response(content=payload, media_type=media_type)


@router.get("/{asset_id}/content")
def get_asset_content(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*MODEL_READ_ROLES)),
):
    asset = _get_visible_asset_or_404(db, asset_id, current_user)
    if asset.asset_type not in {"image", "video", "screenshot"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Asset content preview is only available for image, video or screenshot assets")
    if not os.path.exists(asset.storage_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file missing")
    media_type = {
        "image": "image/jpeg",
        "video": "video/mp4",
        "screenshot": "image/jpeg",
    }.get(asset.asset_type, "application/octet-stream")
    return FileResponse(asset.storage_uri, media_type=media_type, filename=asset.file_name)


@router.post("/upload")
def upload_asset(
    request: Request,
    file: UploadFile = File(..., description="上传文件 / Uploaded image, video or ZIP dataset bundle"),
    sensitivity_level: str = Form(default="L2", description="敏感级别 / Sensitivity level: L1|L2|L3"),
    source_uri: str = Form(default="", description="来源地址 / Optional source URI for traceability"),
    asset_purpose: str = Form(default="inference", description="资产用途 / Asset purpose for training or inference"),
    dataset_label: str = Form(default="", description="数据集标记 / Dataset label used by training/validation"),
    use_case: str = Form(default="", description="业务场景 / Business use case, e.g. railway-defect-inspection"),
    intended_model_code: str = Form(default="", description="目标模型编码 / Intended target model code"),
    buyer_tenant_code: str = Form(default="", description="买家租户编码 / Buyer tenant code (platform uploader only)"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*ASSET_UPLOAD_ROLES)),
):
    original_file_name, ext = _safe_original_file_name(file.filename)

    if sensitivity_level not in {"L1", "L2", "L3"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sensitivity_level")

    if asset_purpose not in ASSET_PURPOSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid asset_purpose")

    _validate_archive_policy(ext, asset_purpose)

    settings = get_settings()
    os.makedirs(settings.asset_repo_path, exist_ok=True)
    buyer_tenant_id = _resolve_buyer_tenant_id(db, current_user, buyer_tenant_code.strip())

    asset_id = str(uuid.uuid4())
    # 流式上传降低内存占用，同时在写入阶段完成大小限制校验。
    # Stream uploads to disk to reduce memory pressure and enforce size limits.
    storage_uri, checksum, file_size = _persist_upload_stream(
        file=file,
        target_dir=settings.asset_repo_path,
        asset_id=asset_id,
        ext=ext,
        max_bytes=settings.asset_upload_max_bytes,
    )

    asset_type = _asset_type_from_extension(ext)

    meta = {
        "size": file_size,
        "extension": ext,
        "asset_purpose": asset_purpose,
    }
    try:
        if asset_type == "archive":
            meta.update(
                _inspect_archive_bundle(
                    storage_uri,
                    max_entries=settings.asset_archive_max_entries,
                    max_uncompressed_bytes=settings.asset_archive_max_uncompressed_bytes,
                )
            )
    except HTTPException:
        if os.path.exists(storage_uri):
            os.remove(storage_uri)
        raise
    if dataset_label.strip():
        meta["dataset_label"] = dataset_label.strip()
    if use_case.strip():
        meta["use_case"] = use_case.strip()
    if intended_model_code.strip():
        meta["intended_model_code"] = intended_model_code.strip()

    source_uri_cleaned = source_uri.strip() or None
    reusable_asset = _find_reusable_asset(
        db,
        file_name=original_file_name,
        asset_type=asset_type,
        sensitivity_level=sensitivity_level,
        checksum=checksum,
        buyer_tenant_id=buyer_tenant_id,
        source_uri=source_uri_cleaned,
        meta=meta,
    )
    if reusable_asset:
        if os.path.exists(storage_uri):
            os.remove(storage_uri)
        record_audit(
            db,
            action=actions.ASSET_UPLOAD,
            resource_type="asset",
            resource_id=reusable_asset.id,
            detail={
                "file_name": reusable_asset.file_name,
                "size": file_size,
                "asset_purpose": meta.get("asset_purpose"),
                "asset_type": reusable_asset.asset_type,
                "archive_resource_count": meta.get("archive_resource_count"),
                "reused": True,
                "reused_existing_asset_id": reusable_asset.id,
            },
            request=request,
            actor=current_user,
        )
        payload = _serialize_asset(reusable_asset)
        payload["reused"] = True
        return payload

    asset = DataAsset(
        id=asset_id,
        file_name=original_file_name,
        asset_type=asset_type,
        storage_uri=storage_uri,
        source_uri=source_uri_cleaned,
        sensitivity_level=sensitivity_level,
        checksum=checksum,
        buyer_tenant_id=buyer_tenant_id,
        meta=meta,
        uploaded_by=current_user.id,
    )
    try:
        db.add(asset)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        if os.path.exists(storage_uri):
            os.remove(storage_uri)
        raise

    record_audit(
        db,
        action=actions.ASSET_UPLOAD,
        resource_type="asset",
        resource_id=asset.id,
        detail={
            "file_name": asset.file_name,
            "size": file_size,
            "sensitivity_level": sensitivity_level,
            "asset_purpose": asset_purpose,
            "asset_type": asset.asset_type,
            "archive_resource_count": meta.get("archive_resource_count"),
            "dataset_label": meta.get("dataset_label"),
            "use_case": meta.get("use_case"),
            "intended_model_code": meta.get("intended_model_code"),
        },
        request=request,
        actor=current_user,
    )
    payload = _serialize_asset(asset)
    payload["reused"] = False
    return payload
