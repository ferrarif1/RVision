from fastapi import APIRouter, Depends

from app.security.dependencies import AuthUser, get_current_user
from app.security.roles import build_permissions, build_ui_capabilities

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def get_me(current_user: AuthUser = Depends(get_current_user)):
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
