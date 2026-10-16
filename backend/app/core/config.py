"""Application configuration. Secrets come only from the environment (never code)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # backend/app/core -> repo root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    ENV: str = "dev"
    DATABASE_URL: str = "postgresql+psycopg://scnc_app:change-me@127.0.0.1:5434/scnc_dev"
    ALEMBIC_DATABASE_URL: str = "postgresql+psycopg://scnc_owner:change-me@127.0.0.1:5434/scnc_dev"
    STORAGE_ROOT: str = "./storage"
    SESSION_COOKIE_NAME: str = "scnc_session"
    SESSION_EXPIRE_MINUTES: int = 480
    SESSION_SECURE_COOKIE: bool = False  # set True when serving over TLS
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
