from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.db.database import get_db
from app.db.models import Device, ModelRelease
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import DEVICE_READ_ROLES, is_buyer_user

router = APIRouter(prefix="/devices", tags=["devices"])

ONLINE_WINDOW_SECONDS = 90


def _compute_device_scope(
    device_code: str,
    releases: list[ModelRelease],
) -> tuple[list[str], bool]:
    buyers: set[str] = set()
    open_to_all_buyers = False
    for release in releases:
        target_devices = release.target_devices or []
        if target_devices and device_code not in target_devices:
            continue
        target_buyers = release.target_buyers or []
        if target_buyers:
            buyers.update(target_buyers)
        else:
            open_to_all_buyers = True
    return sorted(buyers), open_to_all_buyers


def _heartbeat_status(device: Device) -> str:
    if device.status != "ACTIVE":
        return device.status
    if not device.last_seen_at:
        return "OFFLINE"
    if device.last_seen_at >= datetime.utcnow() - timedelta(seconds=ONLINE_WINDOW_SECONDS):
        return "ONLINE"
    return "STALE"


@router.get("")
def list_devices(
    status: str | None = Query(default=None, description="设备状态筛选 / Device status filter"),
    limit: int = Query(default=100, ge=1, le=500, description="返回条数上限 / Max number of returned rows"),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*DEVICE_READ_ROLES)),
):
    devices = db.query(Device).order_by(Device.created_at.desc()).limit(limit).all()
    releases = (
        db.query(ModelRelease)
        .filter(ModelRelease.status == MODEL_RELEASE_STATUS_RELEASED)
        .order_by(ModelRelease.created_at.desc())
        .all()
    )

    payload = []
    for device in devices:
        buyers, open_to_all_buyers = _compute_device_scope(device.code, releases)
        if is_buyer_user(current_user.roles):
            buyer_code = current_user.tenant_code or ""
            if not open_to_all_buyers and buyer_code not in buyers:
                continue

        computed_status = _heartbeat_status(device)
        if status and computed_status != status:
            continue

        buyer_label = "ALL" if open_to_all_buyers else (",".join(buyers) if buyers else "-")
        payload.append(
            {
                "id": device.id,
                "device_id": device.code,
                "name": device.name,
                "buyer": buyer_label,
                "status": computed_status,
                "last_heartbeat": device.last_seen_at,
                "agent_version": device.agent_version or "unknown",
                "created_at": device.created_at,
            }
        )
    return payload
