import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
DEFAULT_DB_PATH = BASE_DIR / "trace.db"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"
    DATABASE_URL: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
    DEMO_DATA_DIR: str = str(REPO_ROOT / "data" / "demo")
    CONTRACT_DIR: str = str(REPO_ROOT / "contract")

settings = Settings()
