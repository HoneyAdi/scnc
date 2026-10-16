"""Engine/session handling. Engines are built lazily from current settings so that
tests (which point DATABASE_URL at the isolated test database) never touch dev.
App code uses the least-privilege app role only.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

_engines: dict[str, object] = {}


def get_engine(url: str | None = None):
    key = url or get_settings().DATABASE_URL
    engine = _engines.get(key)
    if engine is None:
        engine = create_engine(key, pool_pre_ping=True)
        _engines[key] = engine
    return engine


def get_session() -> DbSession:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)()
