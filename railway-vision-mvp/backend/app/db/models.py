import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.constants import MODEL_RELEASE_STATUS_RELEASED
from app.core.constants import MODEL_TYPE_EXPERT
from app.core.constants import MODEL_STATUS_REGISTERED
from app.core.constants import PIPELINE_STATUS_DRAFT
from app.core.constants import TASK_STATUS_PENDING
from app.core.constants import TRAINING_JOB_STATUS_PENDING
from app.core.constants import TRAINING_WORKER_STATUS_ACTIVE
from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(128), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    roles = relationship("Role", secondary="user_roles", back_populates="users")
    tenant = relationship("Tenant")


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_code = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    tenant_type = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    users = relationship("User", secondary="user_roles", back_populates="roles")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    edge_token_hash = Column(String(255), nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TrainingWorker(Base):
    __tablename__ = "training_workers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    worker_code = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default=TRAINING_WORKER_STATUS_ACTIVE, index=True)
    auth_token_hash = Column(String(255), nullable=False)
    host = Column(String(255), nullable=True)
    labels = Column(JSON, nullable=False, default=dict)
    resources = Column(JSON, nullable=False, default=dict)
    last_seen_at = Column(DateTime, nullable=True)
    last_job_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ModelRecord(Base):
    __tablename__ = "models"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_code = Column(String(128), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    model_hash = Column(String(128), nullable=False)
    model_type = Column(String(32), nullable=False, default=MODEL_TYPE_EXPERT, index=True)
    runtime = Column(String(64), nullable=True)
    inputs = Column(JSON, nullable=False, default=dict)
    outputs = Column(JSON, nullable=False, default=dict)
    plugin_name = Column(String(128), nullable=True)
    gpu_mem_mb = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    encrypted_uri = Column(Text, nullable=False)
    signature_uri = Column(Text, nullable=False)
    manifest_uri = Column(Text, nullable=False)
    manifest = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default=MODEL_STATUS_REGISTERED)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    owner_tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("model_code", "version", name="uq_model_code_version"),)


class PipelineRecord(Base):
    __tablename__ = "pipelines"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pipeline_code = Column(String(128), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    router_model_id = Column(String(36), ForeignKey("models.id", ondelete="SET NULL"), nullable=True)
    expert_map = Column(JSON, nullable=False, default=dict)
    thresholds = Column(JSON, nullable=False, default=dict)
    fusion_rules = Column(JSON, nullable=False, default=dict)
    config = Column(JSON, nullable=False, default=dict)
    version = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default=PIPELINE_STATUS_DRAFT, index=True)
    owner_tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("pipeline_code", "version", name="uq_pipeline_code_version"),)


class ModelRelease(Base):
    __tablename__ = "model_releases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_id = Column(String(36), ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    target_devices = Column(JSON, nullable=False, default=list)
    target_buyers = Column(JSON, nullable=False, default=list)
    status = Column(String(32), nullable=False, default=MODEL_RELEASE_STATUS_RELEASED)
    released_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DataAsset(Base):
    __tablename__ = "data_assets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_name = Column(String(255), nullable=False)
    asset_type = Column(String(32), nullable=False)
    storage_uri = Column(Text, nullable=False)
    source_uri = Column(Text, nullable=True)
    sensitivity_level = Column(String(8), nullable=False)
    checksum = Column(String(128), nullable=False)
    buyer_tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    meta = Column("metadata", JSON, nullable=False, default=dict)
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_code = Column(String(128), unique=True, nullable=False, index=True)
    owner_tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    buyer_tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    base_model_id = Column(String(36), ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default=TRAINING_JOB_STATUS_PENDING, index=True)
    training_kind = Column(String(32), nullable=False, default="finetune")
    asset_ids = Column(JSON, nullable=False, default=list)
    validation_asset_ids = Column(JSON, nullable=False, default=list)
    target_model_code = Column(String(128), nullable=False)
    target_version = Column(String(64), nullable=False)
    worker_selector = Column(JSON, nullable=False, default=dict)
    spec = Column(JSON, nullable=False, default=dict)
    output_summary = Column(JSON, nullable=False, default=dict)
    candidate_model_id = Column(String(36), ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_worker_code = Column(String(128), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    dispatch_count = Column(Integer, nullable=False, default=0)


class InferenceTask(Base):
    __tablename__ = "inference_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_id = Column(String(36), ForeignKey("models.id", ondelete="SET NULL"), nullable=True)
    pipeline_id = Column(String(36), ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_id = Column(String(36), ForeignKey("data_assets.id", ondelete="SET NULL"), nullable=True)
    device_code = Column(String(128), nullable=True, index=True)
    task_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default=TASK_STATUS_PENDING)
    buyer_tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    policy = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    dispatch_count = Column(Integer, nullable=False, default=0)


class InferenceResult(Base):
    __tablename__ = "inference_results"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("inference_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    model_id = Column(String(36), ForeignKey("models.id", ondelete="SET NULL"), nullable=True)
    model_hash = Column(String(128), nullable=False)
    result_json = Column(JSON, nullable=False, default=dict)
    buyer_tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    alert_level = Column(String(32), nullable=False, default="INFO")
    screenshot_uri = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class InferenceRun(Base):
    __tablename__ = "inference_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), nullable=False, unique=True, index=True)
    task_id = Column(String(36), ForeignKey("inference_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_id = Column(String(36), ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True, index=True)
    pipeline_version = Column(String(64), nullable=True)
    threshold_version = Column(String(64), nullable=True)
    input_hash = Column(String(128), nullable=False)
    input_summary = Column(JSON, nullable=False, default=dict)
    models_versions = Column(JSON, nullable=False, default=list)
    timings = Column(JSON, nullable=False, default=dict)
    result_summary = Column(JSON, nullable=False, default=dict)
    audit_hash = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="SUCCEEDED")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("inference_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_id = Column(String(36), ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True, index=True)
    reason = Column(Text, nullable=False)
    assigned_to = Column(String(128), nullable=True)
    label_result = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="PENDING")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id = Column(String(36), nullable=True)
    actor_username = Column(String(128), nullable=True)
    actor_role = Column(String(64), nullable=True)
    action = Column(String(128), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)
    detail = Column(JSON, nullable=False, default=dict)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
