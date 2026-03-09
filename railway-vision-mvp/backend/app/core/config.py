from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.brand import BACKEND_APP_NAME, DATABASE_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _default_repo_path(*parts: str) -> str:
    return str((PROJECT_ROOT.joinpath(*parts)).resolve())


def _normalize_runtime_path(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return text
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    return str(path)


def _ensure_runtime_path_inside_workspace(raw: str, *, label: str) -> str:
    normalized = Path(_normalize_runtime_path(raw))
    allowed_roots = [PROJECT_ROOT.resolve()]

    # Docker runtime mounts the backend repo under /app, keep that path valid.
    docker_root = Path("/app")
    if docker_root.exists():
        allowed_roots.append(docker_root.resolve())

    for root in allowed_roots:
        try:
            normalized.relative_to(root)
            return str(normalized)
        except ValueError:
            continue
    raise ValueError(f"{label} must stay inside RVision workspace or /app runtime mount: {normalized}")


class Settings(BaseSettings):
    app_name: str = Field(default=BACKEND_APP_NAME, description="应用名称 / Backend application name")
    app_env: str = Field(default="dev", description="运行环境 / Runtime environment, e.g. dev/staging/prod")

    database_url: str = Field(
        default=f"postgresql+psycopg2://railway:railway123@localhost:5432/{DATABASE_NAME}",
        description="数据库连接串 / SQLAlchemy database connection URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis 连接串 / Redis connection URL")

    jwt_secret: str = Field(default="CHANGE_ME", description="JWT 签名密钥 / JWT signing secret")
    jwt_algorithm: str = Field(default="HS256", description="JWT 算法 / JWT signing algorithm")
    jwt_expires_minutes: int = Field(default=120, description="JWT 过期分钟数 / JWT expiration in minutes")

    model_repo_path: str = Field(default=_default_repo_path("backend", "app", "models_repo"), description="模型仓库存储路径 / Model repository path")
    asset_repo_path: str = Field(default=_default_repo_path("backend", "app", "uploads"), description="资产存储路径 / Uploaded asset storage path")
    asset_upload_max_bytes: int = Field(
        default=268435456,
        description="单个资产上传大小上限（字节） / Max size in bytes for a single uploaded asset",
    )
    asset_archive_max_entries: int = Field(
        default=10000,
        description="单个 ZIP 资产允许的最大归档条目数 / Max number of archive entries allowed in one ZIP asset",
    )
    asset_archive_max_uncompressed_bytes: int = Field(
        default=1073741824,
        description="单个 ZIP 资产允许的最大解压后总大小（字节） / Max total uncompressed bytes allowed in one ZIP asset",
    )
    model_signing_public_key: str = Field(
        default="/app/keys/model_sign_public.pem",
        description="模型包验签公钥路径 / Public key path for model package signature verification",
    )

    audit_export_enabled: bool = Field(default=True, description="是否启用审计导出 / Enable audit export or not")
    training_worker_stale_seconds: int = Field(
        default=300,
        description="训练 Worker 判定为心跳超时的秒数 / Seconds before a training worker is considered stale",
    )
    training_dispatch_timeout_seconds: int = Field(
        default=900,
        description="训练作业从派发到开始执行的最长秒数 / Max seconds allowed between dispatch and start",
    )
    training_running_timeout_seconds: int = Field(
        default=14400,
        description="训练作业 RUNNING 状态允许的最长秒数 / Max seconds allowed for a RUNNING training job",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @model_validator(mode="after")
    def _normalize_storage_paths(self) -> "Settings":
        self.model_repo_path = _ensure_runtime_path_inside_workspace(self.model_repo_path, label="model_repo_path")
        self.asset_repo_path = _ensure_runtime_path_inside_workspace(self.asset_repo_path, label="asset_repo_path")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
