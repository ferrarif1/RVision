from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Device, TrainingWorker, User
from app.security.auth import decode_access_token, verify_password
from app.security.roles import has_any_role

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class AuthUser:
    id: str
    username: str
    roles: list[str]
    tenant_id: str | None = None
    tenant_code: str | None = None
    tenant_type: str | None = None


@dataclass
class EdgeDeviceContext:
    id: str
    code: str
    name: str


@dataclass
class TrainingWorkerContext:
    id: str
    code: str
    name: str


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> AuthUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        if not username:
            raise credentials_exception
    except jwt.PyJWTError as exc:
        raise credentials_exception from exc

    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    if not user:
        raise credentials_exception

    roles = [role.name for role in user.roles]
    tenant = user.tenant
    return AuthUser(
        id=user.id,
        username=user.username,
        roles=roles,
        tenant_id=tenant.id if tenant else None,
        tenant_code=tenant.tenant_code if tenant else None,
        tenant_type=tenant.tenant_type if tenant else None,
    )


def require_roles(*required_roles: str):
    def checker(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not has_any_role(current_user.roles, required_roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return current_user

    return checker


def get_edge_device(
    x_edge_device_code: str = Header(default=""),
    x_edge_token: str = Header(default=""),
    db: Session = Depends(get_db),
) -> EdgeDeviceContext:
    if not x_edge_device_code or not x_edge_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing edge credentials")

    device = db.query(Device).filter(Device.code == x_edge_device_code, Device.status == "ACTIVE").first()
    if not device or not verify_password(x_edge_token, device.edge_token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid edge credentials")

    return EdgeDeviceContext(id=device.id, code=device.code, name=device.name)


def get_training_worker(
    x_training_worker_code: str = Header(default=""),
    x_training_worker_token: str = Header(default=""),
    db: Session = Depends(get_db),
) -> TrainingWorkerContext:
    if not x_training_worker_code or not x_training_worker_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing training worker credentials")

    worker = db.query(TrainingWorker).filter(TrainingWorker.worker_code == x_training_worker_code).first()
    if not worker or worker.status == "INACTIVE" or not verify_password(x_training_worker_token, worker.auth_token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid training worker credentials")

    return TrainingWorkerContext(id=worker.id, code=worker.worker_code, name=worker.name)
