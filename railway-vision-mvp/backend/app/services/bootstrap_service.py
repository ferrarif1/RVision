import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import Base, engine
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
    Base.metadata.create_all(bind=engine)
    # Lightweight migration for environments created before tenant fields existed.
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)",
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS model_type VARCHAR(32) NOT NULL DEFAULT 'expert'",
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS runtime VARCHAR(64)",
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS inputs JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS outputs JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS plugin_name VARCHAR(128)",
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS gpu_mem_mb INTEGER",
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS latency_ms INTEGER",
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS owner_tenant_id VARCHAR(36)",
        "ALTER TABLE model_releases ADD COLUMN IF NOT EXISTS target_buyers JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE data_assets ADD COLUMN IF NOT EXISTS buyer_tenant_id VARCHAR(36)",
        "ALTER TABLE inference_tasks ADD COLUMN IF NOT EXISTS pipeline_id VARCHAR(36)",
        "ALTER TABLE inference_tasks ADD COLUMN IF NOT EXISTS buyer_tenant_id VARCHAR(36)",
        "ALTER TABLE inference_results ADD COLUMN IF NOT EXISTS buyer_tenant_id VARCHAR(36)",
        """
        CREATE TABLE IF NOT EXISTS pipelines (
            id VARCHAR(36) PRIMARY KEY,
            pipeline_code VARCHAR(128) NOT NULL,
            name VARCHAR(255) NOT NULL,
            router_model_id VARCHAR(36) NULL REFERENCES models(id) ON DELETE SET NULL,
            expert_map JSONB NOT NULL DEFAULT '{}'::jsonb,
            thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
            fusion_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            version VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
            owner_tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
            created_by VARCHAR(36) NOT NULL REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_pipeline_code_version UNIQUE (pipeline_code, version)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS inference_runs (
            id VARCHAR(36) PRIMARY KEY,
            job_id VARCHAR(36) NOT NULL UNIQUE,
            task_id VARCHAR(36) NOT NULL REFERENCES inference_tasks(id) ON DELETE CASCADE,
            pipeline_id VARCHAR(36) NULL REFERENCES pipelines(id) ON DELETE SET NULL,
            pipeline_version VARCHAR(64),
            threshold_version VARCHAR(64),
            input_hash VARCHAR(128) NOT NULL,
            input_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            models_versions JSONB NOT NULL DEFAULT '[]'::jsonb,
            timings JSONB NOT NULL DEFAULT '{}'::jsonb,
            result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            audit_hash VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'SUCCEEDED',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS review_queue (
            id VARCHAR(36) PRIMARY KEY,
            job_id VARCHAR(36) NOT NULL,
            task_id VARCHAR(36) NOT NULL REFERENCES inference_tasks(id) ON DELETE CASCADE,
            pipeline_id VARCHAR(36) NULL REFERENCES pipelines(id) ON DELETE SET NULL,
            reason TEXT NOT NULL,
            assigned_to VARCHAR(128),
            label_result VARCHAR(128),
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_models_type_status ON models(model_type, status)",
        "CREATE INDEX IF NOT EXISTS idx_pipelines_code_version ON pipelines(pipeline_code, version)",
        "CREATE INDEX IF NOT EXISTS idx_pipelines_status ON pipelines(status)",
        "CREATE INDEX IF NOT EXISTS idx_pipelines_owner_tenant_id ON pipelines(owner_tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_pipeline_id ON inference_tasks(pipeline_id)",
        "CREATE INDEX IF NOT EXISTS idx_inference_runs_task_id ON inference_runs(task_id)",
        "CREATE INDEX IF NOT EXISTS idx_review_queue_task_id ON review_queue(task_id)",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


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
