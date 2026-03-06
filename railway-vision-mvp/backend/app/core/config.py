from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="railway-vision-mvp-backend", description="应用名称 / Backend application name")
    app_env: str = Field(default="dev", description="运行环境 / Runtime environment, e.g. dev/staging/prod")

    database_url: str = Field(
        default="postgresql+psycopg2://railway:railway123@localhost:5432/railway_vision",
        description="数据库连接串 / SQLAlchemy database connection URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis 连接串 / Redis connection URL")

    jwt_secret: str = Field(default="CHANGE_ME", description="JWT 签名密钥 / JWT signing secret")
    jwt_algorithm: str = Field(default="HS256", description="JWT 算法 / JWT signing algorithm")
    jwt_expires_minutes: int = Field(default=120, description="JWT 过期分钟数 / JWT expiration in minutes")

    model_repo_path: str = Field(default="/app/app/models_repo", description="模型仓库存储路径 / Model repository path")
    asset_repo_path: str = Field(default="/app/app/uploads", description="资产存储路径 / Uploaded asset storage path")
    asset_upload_max_bytes: int = Field(
        default=268435456,
        description="单个资产上传大小上限（字节） / Max size in bytes for a single uploaded asset",
    )
    model_signing_public_key: str = Field(
        default="/app/keys/model_sign_public.pem",
        description="模型包验签公钥路径 / Public key path for model package signature verification",
    )

    audit_export_enabled: bool = Field(default=True, description="是否启用审计导出 / Enable audit export or not")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
