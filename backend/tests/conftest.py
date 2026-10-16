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
