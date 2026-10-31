"""全局配置：EDP_ 前缀环境变量注入，pydantic-settings。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EDP_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://edp_migrator:edp_dev@localhost:15432/edp"
    jwt_secret: str = "dev-secret"
    jwt_alg: str = "HS256"
    access_ttl_seconds: int = 7200
    refresh_ttl_seconds: int = 604800
    admin_initial_password: str = "Admin@123!"
    seed_password: str = "Admin@123!"
    dev_api_key: str = "edp-dev-agent-hub-key"
    idempotency_ttl_seconds: int = 86400
    outbox_max_retries: int = 8
    outbox_backoff_base_seconds: float = 5.0
    app_env: str = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
