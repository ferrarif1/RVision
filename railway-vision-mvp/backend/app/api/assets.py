import hashlib
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import DataAsset, Tenant
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import ASSET_UPLOAD_ROLES, MODEL_READ_ROLES, is_buyer_user, is_platform_user, is_supplier_user
from app.services.audit_service import record_audit

router = APIRouter(prefix="/assets", tags=["assets"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".mp4", ".avi", ".mov"}
ASSET_PURPOSES = {"training", "finetune", "validation", "inference"}
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_FILE_NAME_LENGTH = 255


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


@router.get("")
def list_assets(
    q: str | None = Query(default=None, description="关键词搜索 / Keyword search across file and metadata"),
    asset_type: str | None = Query(default=None, description="资产类型 / Asset type: image or video"),
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


@router.post("/upload")
def upload_asset(
    request: Request,
    file: UploadFile = File(..., description="上传文件 / Uploaded image or video file"),
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

    asset_type = "video" if ext in {".mp4", ".avi", ".mov"} else "image"

    meta = {
        "size": file_size,
        "extension": ext,
        "asset_purpose": asset_purpose,
    }
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
