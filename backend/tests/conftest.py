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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import create_app

APP_ROLE = "scnc_app_test"
# Exact names the disposable test database and its application role must have.
# Verified against the LIVE connection (current_database()/current_user) before
# any test deletes data: a URL substring check alone is not sufficient.
EXPECTED_TEST_DB = "scnc_test"
EXPECTED_TEST_ROLE = "scnc_app_test"
# Session-level advisory lock: two full-suite runs must never share one
# disposable database (row-lock contention + committed-state races produce
# deadlocks and phantom failures). Second runner exits immediately.
SUITE_LOCK_KEY = "scnc_pytest_suite"


def assert_connected_test_db(engine) -> None:
    """Abort unless the LIVE connection is the expected disposable test DB/role.

    Uses current_database()/current_user from the server, not the URL string, so
    a misconfigured or redirected connection can never be wiped. Never logs
    credentials.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        db_name, role = conn.execute(text("SELECT current_database(), current_user")).one()
    if db_name != EXPECTED_TEST_DB or role != EXPECTED_TEST_ROLE:
        raise AssertionError(
            f"refusing destructive test work: connected as {role!r} on database "
            f"{db_name!r}; expected role {EXPECTED_TEST_ROLE!r} on {EXPECTED_TEST_DB!r}"
        )


def live_engine():
    """Engine for a real-commit test, with a fast URL pre-check (the live
    database/role check still runs via assert_connected_test_db)."""
    url = os.environ["TEST_DATABASE_URL"]
    assert "/scnc_test" in url, "fast pre-check: test DB path expected"
    return create_engine(url)


def delete_user_graph(engine, usernames) -> None:
    """Delete ONLY the named users and their dependent rows, FK-safe.

    Never deletes unrelated users, sessions, audit events, accounts, periods,
    settings, roles, or other test data. Safe to call when the rows are absent.
    """
    from sqlalchemy import delete, or_, select
    from sqlalchemy.orm import Session as SaSession

    from app.models.accounting import Account, FinancialPeriod
    from app.models.auth import AuditLog, User, UserRole
    from app.models.auth import Session as DbSession

    names = list(usernames)
    if not names:
        return
    with SaSession(engine) as s:
        ids = s.execute(select(User.id).where(User.username.in_(names))).scalars().all()
        if not ids:
            return
        s.execute(delete(AuditLog).where(AuditLog.actor_id.in_(ids)))
        s.execute(delete(DbSession).where(DbSession.user_id.in_(ids)))
        s.execute(
            delete(FinancialPeriod).where(
                or_(FinancialPeriod.created_by.in_(ids), FinancialPeriod.closed_by.in_(ids))
            )
        )
        s.execute(delete(Account).where(Account.created_by.in_(ids)))
        s.execute(delete(UserRole).where(UserRole.user_id.in_(ids)))
        s.execute(delete(User).where(User.id.in_(ids)))
        s.commit()


def scrub_test_users(engine) -> None:
    """Delete ONLY users whose username matches a known test prefix, plus their
    dependent rows (same scope as the session cleanup). Never deletes unrelated
    rows, so it is safe to call repeatedly inside a test.
    """
    from sqlalchemy import delete, or_, select
    from sqlalchemy.orm import Session as SaSession

    from app.models.accounting import Account, FinancialPeriod
    from app.models.auth import AuditLog
    from app.models.auth import Session as DbSession
    from app.models.auth import User, UserRole

    with SaSession(engine) as s:
        clauses = [User.username.like(p) for p in SCRUB_LIKE_PREFIXES]
        ids = s.execute(select(User.id).where(or_(*clauses))).scalars().all()
        if ids:
            s.execute(delete(AuditLog).where(AuditLog.actor_id.in_(ids)))
            s.execute(delete(DbSession).where(DbSession.user_id.in_(ids)))
            s.execute(delete(FinancialPeriod).where(FinancialPeriod.created_by.in_(ids)))
            s.execute(delete(Account).where(Account.created_by.in_(ids)))
            s.execute(delete(UserRole).where(UserRole.user_id.in_(ids)))
            s.execute(delete(User).where(User.id.in_(ids)))
            s.execute(delete(AuditLog).where(AuditLog.action.like("stress.%")))
            s.commit()


def assert_no_unexpected_users(engine, allowed=()) -> None:
    """Abort (never delete) if committed users exist beyond `allowed`.

    Lets tests that need a globally-clean system fail loudly on stray data
    instead of silently wiping unrelated rows.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session as SaSession

    from app.models.auth import User

    allowed_names = set(allowed)
    with SaSession(engine) as s:
        names = s.execute(select(User.username)).scalars().all()
    unexpected = [n for n in names if n not in allowed_names]
    if unexpected:
        raise AssertionError(
            f"refusing to run: committed users other than {sorted(allowed_names)!r} "
            f"are present: {unexpected!r}"
        )


@pytest.fixture(scope="session", autouse=True)
def _single_runner(app_engine):
    from sqlalchemy import text

    assert_connected_test_db(app_engine)
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
# LEFTOVERS (including from runs killed mid-flight) before tests start — scoped
# strictly to these prefixes; it never deletes unrelated rows. Disposable test
# database only; these patterns must never match real users.
SCRUB_LIKE_PREFIXES = (
    "atomic%", "stress_actor%", "concA%", "concB%", "concC%",
    "ppcA%", "ppcB%", "acctA%", "acctB%", "raceadmin%",
    "setupadmin%", "setupghost%", "setuplate%",
)


@pytest.fixture(scope="session", autouse=True)
def _clean_slate(app_engine, _single_runner):
    assert_connected_test_db(app_engine)
    scrub_test_users(app_engine)
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
    # Browsers always send Origin on POST; the app requires it whenever a
    # session cookie is already present (re-login / switching user).
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "http://testserver"},
    )


@pytest.fixture(autouse=True)
def _reset_accounting_barrier():
    """Keep the test-only concurrency hook inert outside the test that uses it."""
    from app.services import accounting_service

    accounting_service._create_barrier = None
    yield
    accounting_service._create_barrier = None
