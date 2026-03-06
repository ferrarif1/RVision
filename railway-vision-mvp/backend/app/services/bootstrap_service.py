import uuid

from sqlalchemy.orm import Session

from app.db.models import Device, Role, Tenant, User, UserRole
from app.security.auth import hash_password
from app.security.roles import (
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_BUYER_AUDITOR,
    ROLE_BUYER_OPERATOR,
    ROLE_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_PLATFORM_AUDITOR,
    ROLE_PLATFORM_OPERATOR,
    ROLE_SUPPLIER_ENGINEER,
)
from app.services.schema_migration_service import run_schema_migrations

DEFAULT_TENANTS = [
    ("platform-001", "Platform Tenant", "PLATFORM"),
    ("supplier-demo-001", "Supplier Demo Tenant", "SUPPLIER"),
    ("buyer-demo-001", "Buyer Demo Tenant", "BUYER"),
]

DEFAULT_USERS = [
    # 3-party architecture default accounts
    ("platform_admin", "platform123", [ROLE_PLATFORM_ADMIN]),
    ("platform_operator", "platform123", [ROLE_PLATFORM_OPERATOR]),
    ("platform_auditor", "platform123", [ROLE_PLATFORM_AUDITOR]),
    ("supplier_demo", "supplier123", [ROLE_SUPPLIER_ENGINEER]),
    ("buyer_operator", "buyer123", [ROLE_BUYER_OPERATOR]),
    ("buyer_auditor", "buyer123", [ROLE_BUYER_AUDITOR]),
    # Legacy demo accounts (compatibility)
    ("admin", "admin123", [ROLE_ADMIN]),
    ("operator", "operator123", [ROLE_OPERATOR]),
    ("auditor", "auditor123", [ROLE_AUDITOR]),
]

DEFAULT_USER_TENANT_MAP = {
    "platform_admin": "platform-001",
    "platform_operator": "platform-001",
    "platform_auditor": "platform-001",
    "admin": "platform-001",
    "operator": "platform-001",
    "auditor": "platform-001",
    "supplier_demo": "supplier-demo-001",
    "buyer_operator": "buyer-demo-001",
    "buyer_auditor": "buyer-demo-001",
}


def initialize_database() -> None:
    run_schema_migrations()


def bootstrap_defaults(db: Session) -> None:
    tenants: dict[str, Tenant] = {}
    for tenant_code, name, tenant_type in DEFAULT_TENANTS:
        tenant = db.query(Tenant).filter(Tenant.tenant_code == tenant_code).first()
        if not tenant:
            tenant = Tenant(
                id=str(uuid.uuid4()),
                tenant_code=tenant_code,
                name=name,
                tenant_type=tenant_type,
                status="ACTIVE",
            )
            db.add(tenant)
            db.flush()
        tenants[tenant_code] = tenant

    roles = {}
    for role_name in (
        ROLE_PLATFORM_ADMIN,
        ROLE_PLATFORM_OPERATOR,
        ROLE_PLATFORM_AUDITOR,
        ROLE_SUPPLIER_ENGINEER,
        ROLE_BUYER_OPERATOR,
        ROLE_BUYER_AUDITOR,
        ROLE_ADMIN,
        ROLE_OPERATOR,
        ROLE_AUDITOR,
    ):
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            role = Role(name=role_name)
            db.add(role)
            db.flush()
        roles[role_name] = role

    for username, password, role_names in DEFAULT_USERS:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(id=str(uuid.uuid4()), username=username, password_hash=hash_password(password), is_active=True)
            db.add(user)
            db.flush()
        tenant_code = DEFAULT_USER_TENANT_MAP.get(username)
        if tenant_code and user.tenant_id != tenants[tenant_code].id:
            user.tenant_id = tenants[tenant_code].id
            db.add(user)

        for role_name in role_names:
            has_role = (
                db.query(UserRole)
                .filter(UserRole.user_id == user.id, UserRole.role_id == roles[role_name].id)
                .first()
            )
            if not has_role:
                db.add(UserRole(user_id=user.id, role_id=roles[role_name].id))

    device = db.query(Device).filter(Device.code == "edge-01").first()
    if not device:
        device = Device(
            id=str(uuid.uuid4()),
            code="edge-01",
            name="Demo Edge Device",
            status="ACTIVE",
            edge_token_hash=hash_password("EDGE_TOKEN_CHANGE_ME"),
        )
        db.add(device)

    db.commit()
