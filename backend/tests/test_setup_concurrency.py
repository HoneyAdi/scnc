"""Setup concurrency + failure atomicity (real commits on the disposable test DB).

These tests intentionally commit (concurrency cannot be observed inside a
rolled-back fixture transaction). Cleanup is scoped to the users and setup-token
settings this module owns: no shared table is ever emptied, and if unexpected
committed data is present the test aborts instead of deleting it.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.auth import SystemSetting, User
from app.services import bootstrap
from tests.conftest import (
    assert_connected_test_db,
    assert_no_unexpected_users,
    live_engine,
    scrub_test_users,
)

# Per-run unique suffix: concurrent or crashed-and-rerun suites never share rows.
RID = f"{os.getpid()}{uuid.uuid4().hex[:6]}"


def _clear_setup_settings(engine) -> None:
    """Delete ONLY the setup-token settings this module owns (never other settings)."""
    with Session(engine) as s:
        s.execute(
            delete(SystemSetting).where(
                SystemSetting.key.in_(
                    [bootstrap.SETUP_TOKEN_HASH_KEY, bootstrap.SETUP_TOKEN_EXPIRY_KEY]
                )
            )
        )
        s.commit()


def _reset_system(engine) -> None:
    """Return the committed DB to an uninitialized state WITHOUT wiping tables.

    Removes only test-prefixed users (and their dependents) plus the setup-token
    settings; then aborts if any unexpected user remains, rather than deleting it.
    """
    assert_connected_test_db(engine)
    scrub_test_users(engine)
    _clear_setup_settings(engine)
    assert_no_unexpected_users(engine)


@pytest.fixture()
def live():
    engine = live_engine()
    _reset_system(engine)
    yield engine
    _reset_system(engine)
    engine.dispose()


def _fresh_client():
    return TestClient(create_app(), base_url="http://testserver")


def test_concurrent_setup_creates_exactly_one_admin(live):
    with Session(live) as s:
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
    with Session(live) as s:
        assert len(s.execute(select(User)).all()) == 1
        assert s.execute(select(SystemSetting)).all() == []


def test_failed_setup_leaves_nothing_and_token_survives(live):
    with Session(live) as s:
        token = bootstrap.ensure_setup_token(s)

    c = _fresh_client()
    try:
        # Invalid token: rejected, no user, token rows untouched.
        r = c.post(
            "/api/v1/setup/admin",
            json={
                "token": "wrong-token-value-123",
                "username": f"setupghost_{RID}",
                "password": "GhostPass1234!",
            },
        )
        assert r.status_code == 400
        with Session(live) as s:
            assert s.execute(select(User)).all() == []
            assert s.execute(select(SystemSetting)).all() != []

        # The surviving token still works for a legitimate retry.
        r = c.post(
            "/api/v1/setup/admin",
            json={
                "token": token,
                "username": f"setupadmin_{RID}",
                "password": "RealPass123456!",
            },
        )
        assert r.status_code == 201, r.text
    finally:
        c.close()


def test_expired_token_rejected_without_side_effects(live):
    import datetime as dt

    from app.models.auth import utcnow

    with Session(live) as s:
        token = bootstrap.ensure_setup_token(s)
        exp = s.get(SystemSetting, bootstrap.SETUP_TOKEN_EXPIRY_KEY)
        exp.value = {"at": (utcnow() - dt.timedelta(minutes=1)).isoformat()}
        s.add(exp)
        s.commit()

    c = _fresh_client()
    try:
        r = c.post(
            "/api/v1/setup/admin",
            json={
                "token": token,
                "username": f"setuplate_{RID}",
                "password": "LatePass123456!",
            },
        )
        assert r.status_code == 400
        with Session(live) as s:
            assert s.execute(select(User)).all() == []
    finally:
        c.close()
