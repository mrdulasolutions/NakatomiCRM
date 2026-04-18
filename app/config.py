from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://nakatomi:nakatomi@localhost:5432/nakatomi"
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

    CORS_ORIGINS: str = "*"

    # Memory connectors — comma-separated list; each adapter reads its own env vars
    MEMORY_CONNECTORS: str = ""

    # Dashboard — local audit UI, off by default
    DASHBOARD_ENABLED: bool = False


settings = Settings()
