"""Auth atomicity under audit failure + migration compatibility (isolated test DB)."""
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.models.auth import Session as DbSession, User
from tests.conftest import login_as

# Per-run unique suffix: concurrent or crashed-and-rerun suites never share rows.
RID = f"{os.getpid()}{uuid.uuid4().hex[:6]}"


def _committed_counts(engine, username: str):
    conn = engine.connect()
    try:
        with Session(bind=conn) as s:
            user = s.execute(select(User).where(User.username == username)).scalar_one_or_none()
            sessions = (
                s.execute(
                    select(func.count(DbSession.id)).where(DbSession.user_id == user.id)
                ).scalar()
                if user
                else 0
            )
            failed = user.failed_logins if user else None
            return user is not None, sessions, failed
    finally:
        conn.close()


def _quiet_client(db):
    """TestClient that returns 500 responses instead of re-raising them."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, base_url="http://testserver", raise_server_exceptions=False)


def _committed_user(engine, username: str, password: str = "AtomicPass12345!") -> int:
    from sqlalchemy.orm import Session as SaSession

    from app.core.security import hash_password
    from app.models.auth import User

    conn = engine.connect()
    try:
        with SaSession(bind=conn) as s:
            u = User(username=username, password_hash=hash_password(password))
            s.add(u)
            s.commit()
            return u.id
    finally:
        conn.close()


def _scrub_user(engine, username: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.orm import Session as SaSession

    from app.models.auth import AuditLog
    from app.models.auth import Session as DbSession
    from app.models.auth import User

    conn = engine.connect()
    try:
        with SaSession(bind=conn) as s:
            uid = s.execute(select(User.id).where(User.username == username)).scalar_one_or_none()
            if uid is not None:
                s.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
                s.execute(delete(DbSession).where(DbSession.user_id == uid))
                s.execute(delete(User).where(User.id == uid))
                s.commit()
    finally:
        conn.close()


def test_audit_failure_blocks_login_without_partial_state(client, db, app_engine, monkeypatch):
    from app.services import audit_service

    _scrub_user(app_engine, "atomic1_" + RID)
    _committed_user(app_engine, "atomic1_" + RID)

    def boom(*args, **kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(audit_service, "log_event", boom)
    quiet = _quiet_client(db)
    try:
        r = quiet.post("/api/v1/auth/login", json={"username": "atomic1_" + RID, "password": "AtomicPass12345!"})
        assert r.status_code == 500
    finally:
        quiet.close()
    db.rollback()
    _, sessions, _ = _committed_counts(app_engine, "atomic1_" + RID)
    assert sessions == 0, "no usable session may exist without its creation audit"
    _scrub_user(app_engine, "atomic1_" + RID)


def test_audit_failure_blocks_failed_login_counter(client, db, app_engine, monkeypatch):
    from app.services import audit_service

    _scrub_user(app_engine, "atomic2_" + RID)
    _committed_user(app_engine, "atomic2_" + RID)

    def boom(*args, **kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(audit_service, "log_event", boom)
    quiet = _quiet_client(db)
    try:
        r = quiet.post("/api/v1/auth/login", json={"username": "atomic2_" + RID, "password": "wrong-password-x"})
        assert r.status_code == 500
    finally:
        quiet.close()
    db.rollback()
    _, _, failed = _committed_counts(app_engine, "atomic2_" + RID)
    assert failed == 0, "failed-login counter must roll back with its audit event"
    _scrub_user(app_engine, "atomic2_" + RID)


def test_migration_downgrade_upgrade_roundtrip():
    """Alembic downgradeâ†’upgrade on a scratch database; cleaned up afterwards."""
    import subprocess

    env = dict(os.environ)
    env["ENV"] = "test"
    env["CONFIRM_DISPOSABLE"] = "YES"
    env["TEST_DB_HOST"] = "127.0.0.1"
    env["TEST_DB_NAME"] = "scnc_test_migcheck"
    env["TEST_DB_OWNER"] = "scnc_test_owner"
    env["TEST_DB_OWNER_PASSWORD"] = os.environ.get("SCNC_TEST_OWNER_PASSWORD", "")
    if not env["TEST_DB_OWNER_PASSWORD"]:
        pytest.skip("SCNC_TEST_OWNER_PASSWORD not provided; refusing to guess credentials")
    # Fail closed BEFORE any DROP/CREATE: the roundtrip may only ever target a
    # dedicated disposable scratch database, never the live test database
    # (scnc_test) and never anything off-pattern.
    import re

    scratch = env["TEST_DB_NAME"]
    assert re.fullmatch(r"scnc_test_[a-z0-9]+", scratch), (
        f"refusing migration roundtrip: scratch DB {scratch!r} is not disposable"
    )
    assert scratch != "scnc_test", "roundtrip must never target the live test database"
    base = [sys.executable, "-m", "alembic", "-c", "backend\\alembic.ini"]
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parents[2])
    kw = {"cwd": repo_root}
    psql = [
        "C:\\Program Files\\PostgreSQL\\16\\bin\\psql.exe",
        "-U", "scnc_test_owner", "-h", "127.0.0.1", "-p", "5434", "-d", "postgres",
    ]
    try:
        subprocess.run(
            psql + ["-c", "DROP DATABASE IF EXISTS scnc_test_migcheck;"],
            check=True, capture_output=True, **kw, env={**env, "PGPASSWORD": env["TEST_DB_OWNER_PASSWORD"]},
        )
        subprocess.run(
            psql + ["-c", "CREATE DATABASE scnc_test_migcheck OWNER scnc_test_owner;"],
            check=True, capture_output=True, **kw, env={**env, "PGPASSWORD": env["TEST_DB_OWNER_PASSWORD"]},
        )
        env["ALEMBIC_DATABASE_URL"] = (
            "postgresql+psycopg://scnc_test_owner:"
            f"{env['TEST_DB_OWNER_PASSWORD']}@127.0.0.1:5434/scnc_test_migcheck"
        )
        subprocess.run(base + ["upgrade", "head"], check=True, capture_output=True, **kw, env=env)
        subprocess.run(base + ["downgrade", "-1"], check=True, capture_output=True, **kw, env=env)
        subprocess.run(base + ["upgrade", "head"], check=True, capture_output=True, **kw, env=env)
        eng = create_engine(env["ALEMBIC_DATABASE_URL"])
        try:
            with Session(bind=eng.connect()) as s:
                names = {
                    r[0]
                    for r in s.execute(
                        __import__("sqlalchemy").text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                        )
                    ).all()
                }
                for expected in (
                    "users", "roles", "permissions", "user_roles", "role_permissions",
                    "sessions", "audit_log", "system_settings",
                    "financial_periods", "accounts",
                ):
                    assert expected in names, expected
                from app.models.auth import Permission

                assert s.execute(select(func.count(Permission.id))).scalar() >= 12
        finally:
            eng.dispose()
    finally:
        subprocess.run(
            psql + ["-c", "DROP DATABASE IF EXISTS scnc_test_migcheck;"],
            capture_output=True, **kw, env={**env, "PGPASSWORD": env.get("TEST_DB_OWNER_PASSWORD", "")},
        )
