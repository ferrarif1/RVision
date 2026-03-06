from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.audit import actions
from app.db.database import get_db
from app.db.models import User
from app.security.auth import create_access_token, verify_password
from app.security.dependencies import AuthUser, get_current_user
from app.security.roles import build_permissions, build_ui_capabilities
from app.services.audit_service import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(description="用户名 / Username")
    password: str = Field(description="密码 / Password")


class LoginResponse(BaseModel):
    access_token: str = Field(description="访问令牌 / Access token")
    token_type: str = Field(default="bearer", description="令牌类型 / Token type")
    roles: list[str] = Field(description="角色列表 / Role list")
    capabilities: dict[str, bool] = Field(description="前端能力矩阵 / UI capability matrix")
    permissions: list[str] = Field(description="权限点列表 / Flattened permission list")


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username, User.is_active.is_(True)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    roles = [role.name for role in user.roles]
    token = create_access_token(subject=user.username, roles=roles)
    auth_user = AuthUser(id=user.id, username=user.username, roles=roles)

    record_audit(
        db,
        action=actions.LOGIN,
        resource_type="auth",
        resource_id=user.id,
        detail={"username": user.username},
        request=request,
        actor=auth_user,
    )

    return LoginResponse(
        access_token=token,
        roles=roles,
        capabilities=build_ui_capabilities(roles),
        permissions=build_permissions(roles),
    )


@router.get("/me")
def me(current_user: AuthUser = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "roles": current_user.roles,
        "capabilities": build_ui_capabilities(current_user.roles),
        "permissions": build_permissions(current_user.roles),
        "tenant_id": current_user.tenant_id,
        "tenant_code": current_user.tenant_code,
        "tenant_type": current_user.tenant_type,
    }
