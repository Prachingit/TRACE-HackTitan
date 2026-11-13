import os
from pathlib import Path
from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
DEFAULT_DB_PATH = BASE_DIR / "trace.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"
    PORT: int = 8000
    DATABASE_URL: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
    ALLOWED_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )
    ATLAS_DATA_DIR: str = str(BASE_DIR / "data" / "atlas")

    # Auth
    SECRET_KEY: str = "CHANGE_THIS_IN_PRODUCTION_USE_32_RANDOM_BYTES"

    # Storage
    DATA_DIR: str = str(BASE_DIR / "data" / "uploads")

    # GitHub integration (optional)
    GITHUB_TOKEN: Optional[str] = None

    # SMTP (optional — forgot-password only works when all four are set)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: Optional[int] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASS: Optional[str] = None

    # Optional LLM extraction (falls back to deterministic extractor when unset or on error)
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_BASE_URL: str = "https://api.openai.com/v1"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("postgres://"):
                return "postgresql+psycopg://" + v[len("postgres://"):]
            if v.startswith("postgresql://"):
                return "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    @field_validator(
        "SECRET_KEY", "GITHUB_TOKEN", "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_PORT",
        "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL",
        mode="before",
    )
    @classmethod
    def _blank_to_default(cls, v, info):
        if isinstance(v, str) and not v.strip():
            return cls.model_fields[info.field_name].default
        return v

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def smtp_configured(self) -> bool:
        return all([self.SMTP_HOST, self.SMTP_PORT, self.SMTP_USER, self.SMTP_PASS])


settings = Settings()

_DEFAULT_SECRET = "CHANGE_THIS_IN_PRODUCTION_USE_32_RANDOM_BYTES"
if settings.ENV == "production" and (settings.SECRET_KEY == _DEFAULT_SECRET or len(settings.SECRET_KEY) < 32):
    raise RuntimeError("SECRET_KEY must be set to a random value of at least 32 characters when ENV=production.")

