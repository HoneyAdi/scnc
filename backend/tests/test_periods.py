"""Financial periods: validation, lifecycle, permissions, concurrency."""
import datetime as dt
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.accounting import FinancialPeriod
from app.models.auth import AuditLog, User, UserRole
from tests.conftest import (
    assert_connected_test_db,
    delete_user_graph,
    live_engine,
    login_as,
)

# Per-run unique suffix: concurrent or crashed-and-rerun suites never share rows.
RID = f"{os.getpid()}{uuid.uuid4().hex[:6]}"


def _mk_admin(db, username="peradmin", password="PerAdmin12345!"):
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models.auth import Role

    role_id = db.execute(select(Role.id).where(Role.name == "Super Admin")).scalar_one()
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role_id))
    db.commit()
    return user


def _period(client, code="FY26-27", starts="2026-04-01", ends="2027-03-31", name="FY 2026-27"):
    return client.post(
        "/api/v1/periods",
        json={"code": code, "name": name, "starts_on": starts, "ends_on": ends},
        headers={"Origin": "http://testserver"},
    )


def test_period_lifecycle(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    r = _period(client)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["status"] == "open"

    r = client.get("/api/v1/periods")
    assert r.status_code == 200
    assert any(p["code"] == "FY26-27" for p in r.json())

    r = client.post(f"/api/v1/periods/{pid}/close", headers={"Origin": "http://testserver"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"
    assert r.json()["closed_by"] is not None

    # Closing twice is rejected; closed periods have no edit/reopen endpoint.
    assert client.post(f"/api/v1/periods/{pid}/close", headers={"Origin": "http://testserver"}).status_code == 409
    assert client.put(f"/api/v1/periods/{pid}", json={}, headers={"Origin": "http://testserver"}).status_code == 404
    assert client.patch(f"/api/v1/periods/{pid}", json={}, headers={"Origin": "http://testserver"}).status_code in (404, 405)
    assert client.delete(f"/api/v1/periods/{pid}", headers={"Origin": "http://testserver"}).status_code in (404, 405)


def test_period_validation(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    # End before start.
    r = _period(client, code="BAD1", starts="2027-03-31", ends="2026-04-01")
    assert r.status_code == 400
    # Duplicate code.
    assert _period(client, code="DUP").status_code == 201
    assert _period(client, code="DUP", starts="2028-04-01", ends="2029-03-31").status_code == 400
    # Overlapping range (partial and contained).
    assert _period(client, code="OV1", starts="2027-01-01", ends="2027-12-31").status_code == 400
    assert _period(client, code="OV2", starts="2026-05-01", ends="2026-06-01").status_code == 400
    # Adjacent (non-overlapping) range is accepted.
    assert _period(client, code="NEXT", starts="2027-04-01", ends="2028-03-31").status_code == 201
    # Closing a missing period conflicts cleanly.
    assert client.post("/api/v1/periods/99999/close", headers={"Origin": "http://testserver"}).status_code == 409


def test_period_permissions(client, db):
    from tests.test_rbac import _make_user

    _make_user(db, "pview", "PviewPass1234!", "PView", ["periods.view"])
    login_as(client, "pview", "PviewPass1234!")
    assert client.get("/api/v1/periods").status_code == 200
    assert client.post(
        "/api/v1/periods",
        json={"code": "NOP", "name": "n", "starts_on": "2030-04-01", "ends_on": "2031-03-31"},
        headers={"Origin": "http://testserver"},
    ).status_code == 403
    assert client.post("/api/v1/periods/1/close", headers={"Origin": "http://testserver"}).status_code == 403
    # Unauthenticated requests are rejected.
    c2 = client
    c2.cookies.clear()
    assert c2.get("/api/v1/periods").status_code == 401


def test_period_creation_audited(client, db, superadmin):
    from sqlalchemy import select

    login_as(client, "root_tester", "CorrectHorse12!")
    r = _period(client, code="AUDP")
    assert r.status_code == 201
    pid = r.json()["id"]
    rows = db.execute(
        select(AuditLog).where(AuditLog.action.in_(["period.create", "period.close"]))
    ).all()
    assert any(e.action == "period.create" for e in [x[0] for x in rows])
    r = client.post(f"/api/v1/periods/{pid}/close", headers={"Origin": "http://testserver"})
    assert r.status_code == 200
    rows = db.execute(
        select(AuditLog).where(AuditLog.action == "period.close")
    ).all()
    assert len(rows) == 1


def test_concurrent_overlapping_periods_single_win():
    """Two concurrent creations of OVERLAPPING ranges: exactly one wins, the
    other is cleanly rejected (400), and exactly one period exists for the
    contested range.

    Determinism: both requests pass `accounting_service._create_barrier` after
    the code pre-check and before the serializing advisory lock, so they
    provably reach the critical section together. The barrier is bounded (30s).

    Cleanup is strictly scoped to the two users this test creates and their
    dependent rows; no shared table is emptied.
    """
    import threading

    from app.core.security import hash_password
    from app.models.auth import Role
    from app.services import accounting_service

    names = ("ppcA_" + RID, "ppcB_" + RID)
    codes = ("RACE1_" + RID, "RACE2_" + RID)
    starts, ends = "2031-04-01", "2032-03-31"
    starts_d, ends_d = dt.date.fromisoformat(starts), dt.date.fromisoformat(ends)
    engine = live_engine()
    assert_connected_test_db(engine)
    delete_user_graph(engine, names)  # idempotent pre-clean for crashed reruns
    barrier = threading.Barrier(2, timeout=30)
    accounting_service._create_barrier = barrier.wait
    try:
        with Session(engine) as s:
            role_id = s.execute(
                select(Role.id).where(Role.name == "Super Admin")
            ).scalar_one()
            for name in names:
                u = User(username=name, password_hash=hash_password("PpcPass123456!"))
                s.add(u)
                s.flush()
                s.add(UserRole(user_id=u.id, role_id=role_id))
            s.commit()

        def attempt(me: str, code: str) -> int:
            c = TestClient(create_app(), base_url="http://testserver")
            try:
                r = c.post(
                    "/api/v1/auth/login",
                    json={"username": me, "password": "PpcPass123456!"},
                    headers={"Origin": "http://testserver"},
                )
                assert r.status_code == 200, r.text
                return c.post(
                    "/api/v1/periods",
                    json={"code": code, "name": code, "starts_on": starts, "ends_on": ends},
                    headers={"Origin": "http://testserver"},
                ).status_code
            finally:
                c.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(attempt, names[0], codes[0])
            f2 = pool.submit(attempt, names[1], codes[1])
            result = sorted([f1.result(), f2.result()])
        assert result == [201, 400], f"exactly one winner expected, got {result}"
        with Session(engine) as s:
            count = s.execute(
                select(func.count(FinancialPeriod.id)).where(
                    FinancialPeriod.starts_on <= ends_d,
                    FinancialPeriod.ends_on >= starts_d,
                )
            ).scalar()
        assert count == 1, f"expected exactly one period for the contested range, got {count}"
    finally:
        accounting_service._create_barrier = None
        delete_user_graph(engine, names)
        engine.dispose()
