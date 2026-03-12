from dataclasses import dataclass
from datetime import datetime

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.ui_errors import build_ui_error
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
        detail=build_ui_error(
            "auth_token_invalid",
            "登录状态已失效或当前访问令牌不合法。",
            next_step="请重新登录后，再回到刚才的页面继续操作。",
        ),
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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=build_ui_error(
                    "role_forbidden",
                    "当前账号没有权限执行这个操作。",
                    next_step="请切换到具备相应权限的账号，或回到当前角色的默认工作区。",
                ),
            )
        return current_user

    return checker


def get_edge_device(
    x_edge_device_code: str = Header(default=""),
    x_edge_token: str = Header(default=""),
    x_edge_agent_version: str = Header(default=""),
    db: Session = Depends(get_db),
) -> EdgeDeviceContext:
    if not x_edge_device_code or not x_edge_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_ui_error(
                "edge_credentials_missing",
                "边缘设备凭据缺失，当前设备不能继续拉取任务。",
                next_step="请检查 EDGE_DEVICE_CODE 和 EDGE_TOKEN 后重新启动 edge-agent。",
            ),
        )

    device = db.query(Device).filter(Device.code == x_edge_device_code, Device.status == "ACTIVE").first()
    if not device or not verify_password(x_edge_token, device.edge_token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_ui_error(
                "edge_credentials_invalid",
                "边缘设备凭据不正确，当前设备不能执行任务。",
                next_step="请确认设备编码、边缘令牌和设备状态后重新连接。",
            ),
        )
    device.last_seen_at = datetime.utcnow()
    if x_edge_agent_version.strip():
        device.agent_version = x_edge_agent_version.strip()[:64]
    db.add(device)
    db.commit()

    return EdgeDeviceContext(id=device.id, code=device.code, name=device.name)


def get_training_worker(
    x_training_worker_code: str = Header(default=""),
    x_training_worker_token: str = Header(default=""),
    db: Session = Depends(get_db),
) -> TrainingWorkerContext:
    if not x_training_worker_code or not x_training_worker_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_ui_error(
                "training_worker_credentials_missing",
                "训练机器凭据缺失，当前机器不能继续拉取训练作业。",
                next_step="请重新生成训练机器令牌，或重新执行本机训练机器启动命令。",
            ),
        )

    worker = db.query(TrainingWorker).filter(TrainingWorker.worker_code == x_training_worker_code).first()
    if not worker or worker.status == "INACTIVE" or not verify_password(x_training_worker_token, worker.auth_token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_ui_error(
                "training_worker_credentials_invalid",
                "训练机器凭据不正确，或当前训练机器已停用。",
                next_step="请刷新训练中心检查机器状态，并重新登记训练机器后再试。",
            ),
        )

    return TrainingWorkerContext(id=worker.id, code=worker.worker_code, name=worker.name)
