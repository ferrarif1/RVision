from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "railway-vision-mvp-backend"
    app_env: str = "dev"

    database_url: str = "postgresql+psycopg2://railway:railway123@localhost:5432/railway_vision"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "CHANGE_ME"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 120

    model_repo_path: str = "/app/app/models_repo"
    asset_repo_path: str = "/app/app/uploads"
    model_signing_public_key: str = "/app/keys/model_sign_public.pem"

    audit_export_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
