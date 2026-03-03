import hashlib
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import DataAsset, Tenant
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import ASSET_UPLOAD_ROLES, is_buyer_user, is_platform_user
from app.services.audit_service import record_audit

router = APIRouter(prefix="/assets", tags=["assets"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".mp4", ".avi", ".mov"}
ASSET_PURPOSES = {"training", "finetune", "validation", "inference"}


@router.post("/upload")
def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    sensitivity_level: str = Form(default="L2"),
    source_uri: str = Form(default=""),
    asset_purpose: str = Form(default="inference"),
    dataset_label: str = Form(default=""),
    use_case: str = Form(default=""),
    intended_model_code: str = Form(default=""),
    buyer_tenant_code: str = Form(default=""),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*ASSET_UPLOAD_ROLES)),
):
    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")

    if sensitivity_level not in {"L1", "L2", "L3"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sensitivity_level")

    if asset_purpose not in ASSET_PURPOSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid asset_purpose")

    settings = get_settings()
    os.makedirs(settings.asset_repo_path, exist_ok=True)

    file_bytes = file.file.read()
    checksum = hashlib.sha256(file_bytes).hexdigest()

    asset_id = str(uuid.uuid4())
    safe_name = f"{asset_id}{ext}"
    storage_uri = os.path.join(settings.asset_repo_path, safe_name)

    with open(storage_uri, "wb") as f:
        f.write(file_bytes)

    asset_type = "video" if ext in {".mp4", ".avi", ".mov"} else "image"
    buyer_tenant_id = None
    if is_buyer_user(current_user.roles):
        buyer_tenant_id = current_user.tenant_id
    elif is_platform_user(current_user.roles) and buyer_tenant_code:
        tenant = (
            db.query(Tenant)
            .filter(Tenant.tenant_code == buyer_tenant_code, Tenant.tenant_type == "BUYER", Tenant.status == "ACTIVE")
            .first()
        )
        if not tenant:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid buyer_tenant_code")
        buyer_tenant_id = tenant.id

    meta = {
        "size": len(file_bytes),
        "extension": ext,
        "asset_purpose": asset_purpose,
    }
    if dataset_label.strip():
        meta["dataset_label"] = dataset_label.strip()
    if use_case.strip():
        meta["use_case"] = use_case.strip()
    if intended_model_code.strip():
        meta["intended_model_code"] = intended_model_code.strip()

    asset = DataAsset(
        id=asset_id,
        file_name=file.filename,
        asset_type=asset_type,
        storage_uri=storage_uri,
        source_uri=source_uri or None,
        sensitivity_level=sensitivity_level,
        checksum=checksum,
        buyer_tenant_id=buyer_tenant_id,
        meta=meta,
        uploaded_by=current_user.id,
    )
    db.add(asset)
    db.commit()

    record_audit(
        db,
        action=actions.ASSET_UPLOAD,
        resource_type="asset",
        resource_id=asset.id,
        detail={
            "file_name": asset.file_name,
            "sensitivity_level": sensitivity_level,
            "asset_purpose": asset_purpose,
            "dataset_label": meta.get("dataset_label"),
            "use_case": meta.get("use_case"),
            "intended_model_code": meta.get("intended_model_code"),
        },
        request=request,
        actor=current_user,
    )

    return {
        "id": asset.id,
        "file_name": asset.file_name,
        "asset_type": asset.asset_type,
        "sensitivity_level": asset.sensitivity_level,
        "buyer_tenant_id": asset.buyer_tenant_id,
        "checksum": asset.checksum,
        "meta": asset.meta,
    }
