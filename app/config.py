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

    # Email + calendar background pollers. Disabled by default so a fresh
    # deploy doesn't try to poll a misconfigured IMAP host on every loop.
    EMAIL_POLLER_ENABLED: bool = False
    EMAIL_POLL_INTERVAL_SECONDS: int = 300
    CALENDAR_POLLER_ENABLED: bool = False
    CALENDAR_POLL_INTERVAL_SECONDS: int = 600

    # Dashboard — local audit UI, off by default
    DASHBOARD_ENABLED: bool = False

    # Public origin for OAuth/SSO redirects (e.g. https://crm.example.com).
    # Falls back to request Host headers when empty.
    PUBLIC_BASE_URL: str = ""

    # Optional OpenTelemetry (see app/otel.py, docs/OBSERVABILITY.md)
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "nakatomi"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_HEADERS: str = ""

    # Optional SSO (Google / GitHub). Empty client_id → provider disabled.
    SSO_GOOGLE_CLIENT_ID: str = ""
    SSO_GOOGLE_CLIENT_SECRET: str = ""
    SSO_GITHUB_CLIENT_ID: str = ""
    SSO_GITHUB_CLIENT_SECRET: str = ""
    # When true, first-time SSO users get a personal workspace auto-created.
    SSO_AUTO_CREATE_WORKSPACE: bool = True


settings = Settings()
