"""Setup concurrency + failure atomicity (real commits on the disposable test DB).

These tests intentionally commit (concurrency cannot be observed inside a
rolled-back fixture transaction) and clean up everything they create.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.accounting import Account, FinancialPeriod
from app.models.auth import AuditLog, Session as DbSession, SystemSetting, User, UserRole
from app.services import bootstrap

# Per-run unique suffix: concurrent or crashed-and-rerun suites never share rows.
RID = f"{os.getpid()}{uuid.uuid4().hex[:6]}"


def _engine():
    url = os.environ["TEST_DATABASE_URL"]
    assert "/scnc_test" in url
    return create_engine(url)


def _wipe(engine):
    # Order respects FK RESTRICT guards (audit/sessions/periods/accounts reference users).
    with Session(engine) as s:
        s.execute(delete(AuditLog))
        s.execute(delete(DbSession))
        s.execute(delete(FinancialPeriod))
        s.execute(delete(Account))
        s.execute(delete(UserRole))
        s.execute(delete(User))
        s.execute(delete(SystemSetting))
        s.commit()


@pytest.fixture()
def live():
    engine = _engine()
    _wipe(engine)
    yield engine
    _wipe(engine)
    engine.dispose()


def _fresh_client():
    return TestClient(create_app(), base_url="http://testserver")


def test_concurrent_setup_creates_exactly_one_admin(live):
    with Session(_engine()) as s:
        token = bootstrap.ensure_setup_token(s)
    assert token

    def attempt(i: int):
        c = _fresh_client()
        try:
            r = c.post(
                "/api/v1/setup/admin",
                json={
                    "token": token,
                    "username": f"raceadmin_{RID}_{i}",
                    "password": "RacePass123456!",
                },
            )
            return r.status_code
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(attempt, range(6)))

    assert codes.count(201) == 1, codes
    assert codes.count(400) == 5, codes
    with Session(_engine()) as s:
        assert s.execute(select(User)).all().__len__() == 1
        assert s.execute(select(SystemSetting)).all() == []


def test_failed_setup_leaves_nothing_and_token_survives(live):
    with Session(_engine()) as s:
        token = bootstrap.ensure_setup_token(s)

    c = _fresh_client()
    try:
        # Invalid token: rejected, no user, token rows untouched.
        r = c.post(
            "/api/v1/setup/admin",
            json={"token": "wrong-token-value-123", "username": "ghost1", "password": "GhostPass1234!"},
        )
        assert r.status_code == 400
        with Session(_engine()) as s:
            assert s.execute(select(User)).all() == []
            assert s.execute(select(SystemSetting)).all() != []

        # The surviving token still works for a legitimate retry.
        r = c.post(
            "/api/v1/setup/admin",
            json={"token": token, "username": "realadmin", "password": "RealPass123456!"},
        )
        assert r.status_code == 201, r.text
    finally:
        c.close()


def test_expired_token_rejected_without_side_effects(live):
    import datetime as dt

    from app.models.auth import utcnow

    with Session(_engine()) as s:
        token = bootstrap.ensure_setup_token(s)
        exp = s.get(SystemSetting, bootstrap.SETUP_TOKEN_EXPIRY_KEY)
        exp.value = {"at": (utcnow() - dt.timedelta(minutes=1)).isoformat()}
        s.add(exp)
        s.commit()

    c = _fresh_client()
    try:
        r = c.post(
            "/api/v1/setup/admin",
            json={"token": token, "username": "lateadmin", "password": "LatePass123456!"},
        )
        assert r.status_code == 400
        with Session(_engine()) as s:
            assert s.execute(select(User)).all() == []
    finally:
        c.close()
