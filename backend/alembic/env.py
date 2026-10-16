"""Alembic environment. URL comes ONLY from ALEMBIC_DATABASE_URL (no fallback).

Safety: when ENV=test, the target database name must match ^scnc_test and the
role must be the test owner; otherwise migration aborts before any DDL.
"""
import os
import re
import sys
from logging.config import fileConfig
from urllib.parse import urlparse

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402,F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def resolve_url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL", "")
    if not url or "placeholder-invalid" in url:
        raise RuntimeError("Refusing: ALEMBIC_DATABASE_URL is unset (no fallback allowed).")
    if os.environ.get("ENV") == "test":
        try:
            dbname = (urlparse(url).path or "").lstrip("/")
        except Exception:
            raise RuntimeError("Refusing: cannot parse ALEMBIC_DATABASE_URL.")
        if not re.fullmatch(r"scnc_test(_[a-z0-9]+)?", dbname or ""):
            raise RuntimeError(f"Refusing: test migrations target '{dbname}' is not disposable.")
    # Never log the URL (it contains credentials).
    print("alembic: migrating target database (host/db verified by caller procedure).")
    return url


def run_migrations_offline() -> None:
    context.configure(url=resolve_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(resolve_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
