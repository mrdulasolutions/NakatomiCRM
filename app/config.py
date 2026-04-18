from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://nakatomi:nakatomi@localhost:5432/nakatomi"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Railway + some cloud Postgres providers emit ``postgres://`` and
        plain ``postgresql://``. We need ``postgresql+psycopg://`` so
        SQLAlchemy picks the psycopg3 driver. Rewrite on read so the caller
        doesn't have to care."""
        if not isinstance(v, str) or "+" in v.split("://", 1)[0]:
            return v
        if v.startswith("postgres://"):
            return "postgresql+psycopg://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            return "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    SECRET_KEY: str = "insecure-dev-key-change-me"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_PATH: str = "./data/files"
    S3_BUCKET: str = ""
    S3_REGION: str = "us-east-1"
    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""

    WEBHOOK_TIMEOUT_SECONDS: int = 10
    WEBHOOK_MAX_RETRIES: int = 3
    # Disable in tests so process_pending_deliveries() calls don't race the worker.
    WEBHOOK_WORKER_ENABLED: bool = True

    # Per-API-key rate limit (fixed 60-second window). 0 disables the default;
    # per-key overrides on ApiKey.rate_limit_per_minute still apply.
    API_KEY_RATE_LIMIT_PER_MINUTE: int = 0

    CORS_ORIGINS: str = "*"

    # Memory connectors — comma-separated list; each adapter reads its own env vars
    MEMORY_CONNECTORS: str = ""

    # Dashboard — local audit UI, off by default
    DASHBOARD_ENABLED: bool = False


settings = Settings()
