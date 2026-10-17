"""Pytest configuration: isolated test database, per-test rollback, no prod contact.

Required env (caller pre-sets; never default to a production database):
  ENV=test
  TEST_DATABASE_URL        (role scnc_app_test)
  TEST_ALEMBIC_DATABASE_URL (role scnc_test_owner, migrations only)
"""
import os

# Point the application at the isolated test database through the NORMAL settings
# path (DATABASE_URL), so tests exercise the real configuration wiring. Guarded:
# refuse anything that is not an scnc_test database, and never touch production.
_TEST_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://scnc_app_test:x@localhost:5434/scnc_test",
)
assert os.environ.get("ENV") == "test", "ENV must be 'test' for the suite"
assert "/scnc_test" in _TEST_URL, f"refusing non-test database URL: {_TEST_URL!r}"
assert _TEST_URL.split("@")[0].startswith("postgresql+psycopg://scnc_app_test:"), (
    "test runner must connect as scnc_app_test"
)
os.environ["DATABASE_URL"] = _TEST_URL
os.environ["STORAGE_ROOT"] = "/tmp/scnc_test_storage" if os.name != "nt" else (
    os.environ.get("TEMP", ".") + "\\scnc_test_storage"
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import create_app

APP_ROLE = "scnc_app_test"
# Session-level advisory lock: two full-suite runs must never share one
# disposable database (row-lock contention + committed-state races produce
# deadlocks and phantom failures). Second runner exits immediately.
SUITE_LOCK_KEY = "scnc_pytest_suite"


@pytest.fixture(scope="session", autouse=True)
def _single_runner(app_engine):
    from sqlalchemy import text

    conn = app_engine.connect()
    try:
        free = conn.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": SUITE_LOCK_KEY}
        ).scalar()
        if not free:
            conn.close()
            pytest.exit("another pytest run holds the suite lock on this test database")
        yield conn
    finally:
        try:
            conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": SUITE_LOCK_KEY})
        finally:
            conn.close()


# Real-commit tests use usernames starting with one of these prefixes plus a
# per-run unique suffix (pid + randomness), so two suite runs — concurrent or
# crashed-and-rerun — can never share rows. The session fixture removes any
# leftovers (including from runs killed mid-flight) before tests start.
# Disposable test database only; these patterns must never match real users.
SCRUB_LIKE_PREFIXES = (
    "atomic%", "stress_actor%", "concA%", "concB%", "concC%", "ppcA%", "ppcB%", "raceadmin%",
)


@pytest.fixture(scope="session", autouse=True)
def _clean_slate(app_engine, _single_runner):
    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session as SaSession

    from app.models.accounting import FinancialPeriod
    from app.models.auth import AuditLog
    from app.models.auth import Session as DbSession
    from app.models.auth import User, UserRole

    with SaSession(bind=app_engine.connect()) as s:
        user_clauses = [User.username.like(p) for p in SCRUB_LIKE_PREFIXES]
        ids = s.execute(
            select(User.id).where(or_(*user_clauses))
        ).scalars().all()
        if ids:
            s.execute(delete(AuditLog).where(AuditLog.actor_id.in_(ids)))
            s.execute(delete(DbSession).where(DbSession.user_id.in_(ids)))
            s.execute(delete(FinancialPeriod).where(FinancialPeriod.created_by.in_(ids)))
            s.execute(delete(UserRole).where(UserRole.user_id.in_(ids)))
            s.execute(delete(User).where(User.id.in_(ids)))
            s.execute(delete(AuditLog).where(AuditLog.action.like("stress.%")))
            s.commit()
    yield


@pytest.fixture(scope="session")
def app_engine():
    return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


@pytest.fixture()
def db(app_engine):
    conn = app_engine.connect()
    txn = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    txn.rollback()
    conn.close()


@pytest.fixture()
def client(db: Session):
    app = create_app()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app, base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def superadmin(db: Session):
    """A Super Admin user created directly in the test transaction."""
    from app.core.security import hash_password
    from app.models.auth import Role, User, UserRole

    role_id = db.execute(
        __import__("sqlalchemy").select(Role.id).where(Role.name == "Super Admin")
    ).scalar_one()
    user = User(username="root_tester", password_hash=hash_password("CorrectHorse12!"))
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role_id))
    db.commit()
    return user


def login_as(client: TestClient, username: str, password: str):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})
