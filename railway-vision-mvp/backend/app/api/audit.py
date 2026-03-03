from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AuditLog
from app.security.dependencies import AuthUser, require_roles
from app.security.roles import AUDIT_READ_ROLES

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def query_audit_logs(
    action: str | None = None,
    actor_username: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*AUDIT_READ_ROLES)),
):
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())

    if action:
        query = query.filter(AuditLog.action == action)
    if actor_username:
        query = query.filter(AuditLog.actor_username == actor_username)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if start_time:
        query = query.filter(AuditLog.created_at >= start_time)
    if end_time:
        query = query.filter(AuditLog.created_at <= end_time)

    rows = query.limit(min(limit, 1000)).all()
    return [
        {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "actor_username": row.actor_username,
            "actor_role": row.actor_role,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "detail": row.detail,
            "ip_address": row.ip_address,
            "created_at": row.created_at,
        }
        for row in rows
    ]
