"""Role constants and compatibility mappings for 3-party architecture."""

from app.core.constants import PERMISSION_ASSET_UPLOAD
from app.core.constants import PERMISSION_AUDIT_READ
from app.core.constants import PERMISSION_DASHBOARD_VIEW
from app.core.constants import PERMISSION_DATA_L3_READ
from app.core.constants import PERMISSION_MODEL_APPROVE
from app.core.constants import PERMISSION_MODEL_RELEASE
from app.core.constants import PERMISSION_MODEL_SUBMIT
from app.core.constants import PERMISSION_MODEL_VIEW
from app.core.constants import PERMISSION_RESULT_READ
from app.core.constants import PERMISSION_TASK_CREATE
from app.core.constants import PERMISSION_TRAINING_JOB_CREATE
from app.core.constants import PERMISSION_TRAINING_JOB_VIEW
from app.core.constants import PERMISSION_TRAINING_WORKER_MANAGE

ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_PLATFORM_OPERATOR = "platform_operator"
ROLE_PLATFORM_AUDITOR = "platform_auditor"
ROLE_SUPPLIER_ENGINEER = "supplier_engineer"
ROLE_BUYER_OPERATOR = "buyer_operator"
ROLE_BUYER_AUDITOR = "buyer_auditor"

# Legacy roles kept for backward compatibility in demos/scripts.
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_AUDITOR = "auditor"

ROLE_EQUIVALENCE: dict[str, set[str]] = {
    ROLE_PLATFORM_ADMIN: {ROLE_PLATFORM_ADMIN, ROLE_ADMIN},
    ROLE_ADMIN: {ROLE_ADMIN, ROLE_PLATFORM_ADMIN},
    ROLE_PLATFORM_OPERATOR: {ROLE_PLATFORM_OPERATOR, ROLE_OPERATOR},
    ROLE_OPERATOR: {ROLE_OPERATOR, ROLE_PLATFORM_OPERATOR},
    ROLE_PLATFORM_AUDITOR: {ROLE_PLATFORM_AUDITOR, ROLE_AUDITOR},
    ROLE_AUDITOR: {ROLE_AUDITOR, ROLE_PLATFORM_AUDITOR},
    ROLE_SUPPLIER_ENGINEER: {ROLE_SUPPLIER_ENGINEER},
    ROLE_BUYER_OPERATOR: {ROLE_BUYER_OPERATOR},
    ROLE_BUYER_AUDITOR: {ROLE_BUYER_AUDITOR},
}


def expand_roles(roles: list[str] | set[str] | tuple[str, ...]) -> set[str]:
    expanded: set[str] = set()
    for role in roles:
        expanded.update(ROLE_EQUIVALENCE.get(role, {role}))
    return expanded


def has_any_role(user_roles: list[str], required_roles: tuple[str, ...]) -> bool:
    return bool(expand_roles(user_roles).intersection(expand_roles(required_roles)))


def is_platform_user(user_roles: list[str]) -> bool:
    expanded = expand_roles(user_roles)
    return bool(
        expanded.intersection(
            {
                ROLE_PLATFORM_ADMIN,
                ROLE_PLATFORM_OPERATOR,
                ROLE_PLATFORM_AUDITOR,
                ROLE_ADMIN,
                ROLE_OPERATOR,
                ROLE_AUDITOR,
            }
        )
    )


def is_supplier_user(user_roles: list[str]) -> bool:
    return ROLE_SUPPLIER_ENGINEER in expand_roles(user_roles)


def is_buyer_user(user_roles: list[str]) -> bool:
    expanded = expand_roles(user_roles)
    return bool(expanded.intersection({ROLE_BUYER_OPERATOR, ROLE_BUYER_AUDITOR}))


MODEL_READ_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PLATFORM_OPERATOR,
    ROLE_PLATFORM_AUDITOR,
    ROLE_SUPPLIER_ENGINEER,
    ROLE_BUYER_OPERATOR,
    ROLE_BUYER_AUDITOR,
)

MODEL_SUBMIT_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_SUPPLIER_ENGINEER)
MODEL_APPROVE_ROLES = (ROLE_PLATFORM_ADMIN,)
MODEL_RELEASE_ROLES = (ROLE_PLATFORM_ADMIN,)

ASSET_UPLOAD_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PLATFORM_OPERATOR, ROLE_BUYER_OPERATOR)
TASK_CREATE_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PLATFORM_OPERATOR, ROLE_BUYER_OPERATOR)
TASK_READ_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PLATFORM_OPERATOR,
    ROLE_PLATFORM_AUDITOR,
    ROLE_BUYER_OPERATOR,
    ROLE_BUYER_AUDITOR,
)
RESULT_READ_ROLES = TASK_READ_ROLES
AUDIT_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PLATFORM_AUDITOR)
TRAINING_JOB_CREATE_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PLATFORM_OPERATOR)
TRAINING_JOB_READ_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PLATFORM_OPERATOR,
    ROLE_PLATFORM_AUDITOR,
    ROLE_SUPPLIER_ENGINEER,
)
TRAINING_WORKER_ADMIN_ROLES = (ROLE_PLATFORM_ADMIN,)


def build_ui_capabilities(user_roles: list[str]) -> dict[str, bool]:
    """Build a stable capability map for frontend role-based rendering."""
    return {
        "model_view": has_any_role(user_roles, MODEL_READ_ROLES),
        "model_submit": has_any_role(user_roles, MODEL_SUBMIT_ROLES),
        "model_approve": has_any_role(user_roles, MODEL_APPROVE_ROLES),
        "model_release": has_any_role(user_roles, MODEL_RELEASE_ROLES),
        "asset_upload": has_any_role(user_roles, ASSET_UPLOAD_ROLES),
        "task_create": has_any_role(user_roles, TASK_CREATE_ROLES),
        "result_read": has_any_role(user_roles, RESULT_READ_ROLES),
        "audit_read": has_any_role(user_roles, AUDIT_READ_ROLES),
        "training_job_view": has_any_role(user_roles, TRAINING_JOB_READ_ROLES),
        "training_job_create": has_any_role(user_roles, TRAINING_JOB_CREATE_ROLES),
        "training_worker_manage": has_any_role(user_roles, TRAINING_WORKER_ADMIN_ROLES),
    }


def build_permissions(user_roles: list[str]) -> list[str]:
    """
    Build canonical permission strings for frontend capability-based rendering.
    Keep this centralized so backend RBAC and frontend visibility remain aligned.
    """
    caps = build_ui_capabilities(user_roles)
    permissions: list[str] = [PERMISSION_DASHBOARD_VIEW]

    if caps["model_view"]:
        permissions.append(PERMISSION_MODEL_VIEW)
    if caps["model_submit"]:
        permissions.append(PERMISSION_MODEL_SUBMIT)
    if caps["model_approve"]:
        permissions.append(PERMISSION_MODEL_APPROVE)
    if caps["model_release"]:
        permissions.append(PERMISSION_MODEL_RELEASE)
    if caps["asset_upload"]:
        permissions.append(PERMISSION_ASSET_UPLOAD)
    if caps["task_create"]:
        permissions.append(PERMISSION_TASK_CREATE)
    if caps["result_read"]:
        permissions.append(PERMISSION_RESULT_READ)
    if caps["audit_read"]:
        permissions.append(PERMISSION_AUDIT_READ)
    if caps["training_job_view"]:
        permissions.append(PERMISSION_TRAINING_JOB_VIEW)
    if caps["training_job_create"]:
        permissions.append(PERMISSION_TRAINING_JOB_CREATE)
    if caps["training_worker_manage"]:
        permissions.append(PERMISSION_TRAINING_WORKER_MANAGE)

    # L3 read is intentionally strict.
    if has_any_role(user_roles, (ROLE_PLATFORM_ADMIN, ROLE_PLATFORM_AUDITOR, ROLE_ADMIN, ROLE_AUDITOR)):
        permissions.append(PERMISSION_DATA_L3_READ)

    return sorted(permissions)
