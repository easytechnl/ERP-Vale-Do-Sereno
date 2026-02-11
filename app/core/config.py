from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = Field(default="sqlite:///./data/erp_finance.db")
    SECRET_KEY: str = Field(default="change-me")
    SESSION_COOKIE_NAME: str = Field(default="erp_session")

    STORAGE_DIR: str = Field(default="./data/storage")

    ADMIN_EMAIL: str = Field(default="admin@local")
    ADMIN_PASSWORD: str = Field(default="Admin@123")
    ADMIN_NAME: str = Field(default="Administrador")

    SMTP_HOST: str = Field(default="smtp.office365.com")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASS: str = Field(default="")
    SMTP_FROM: str = Field(default="financeiro@empresa.com")
    SMTP_TLS: bool = Field(default=True)
    EMAIL_REMINDER_INTERVAL_MINUTES: int = Field(default=60)
    EMAIL_REMINDER_STARTUP_DELAY_SECONDS: int = Field(default=20)

    # PostgreSQL tools (optional)
    PG_BIN: str = Field(default="")
    PG_DUMP_PATH: str = Field(default="")
    PG_RESTORE_PATH: str = Field(default="")
    PG_PSQL_PATH: str = Field(default="")

settings = Settings()
