from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.security.dependencies import AuthUser


def record_audit(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: dict[str, Any] | None,
    request: Request | None = None,
    actor: AuthUser | None = None,
    actor_role: str | None = None,
) -> None:
    ip_address = request.client.host if request and request.client else None
    role_to_store = actor_role
    if not role_to_store and actor and actor.roles:
        role_to_store = actor.roles[0]

    audit = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_username=actor.username if actor else None,
        actor_role=role_to_store,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail or {},
        ip_address=ip_address,
    )
    db.add(audit)
    db.commit()
