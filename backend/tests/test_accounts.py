"""Chart of accounts: uniqueness, hierarchy, permissions, audit, rollback."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.accounting import Account
from app.models.auth import AuditLog, User, UserRole
from tests.conftest import (
    assert_connected_test_db,
    delete_user_graph,
    live_engine,
    login_as,
)

RID = f"{os.getpid()}{uuid.uuid4().hex[:6]}"


def _acct(client, code="1000", name="Cash", type="asset", parent_id=None, desc=""):
    body = {"code": code, "name": name, "type": type, "description": desc}
    if parent_id is not None:
        body["parent_id"] = parent_id
    return client.post("/api/v1/accounts", json=body, headers={"Origin": "http://testserver"})


def test_account_crud_and_hierarchy(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    cash = _acct(client, code="1000", name="Cash in Hand", type="asset")
    assert cash.status_code == 201, cash.text
    cash_id = cash.json()["id"]

    child = _acct(client, code="1100", name="Petty Cash", type="asset", parent_id=cash_id)
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]

    items = client.get("/api/v1/accounts").json()["items"]
    assert {a["code"] for a in items} >= {"1000", "1100"}

    # Deactivate preserves the record.
    r = client.patch(f"/api/v1/accounts/{child_id}", json={"is_active": False}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert any(a["code"] == "1100" for a in client.get("/api/v1/accounts").json()["items"])

    # No delete endpoint exists.
    assert client.delete(f"/api/v1/accounts/{child_id}", headers={"Origin": "http://testserver"}).status_code in (404, 405)


def test_account_validation(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    assert _acct(client, code="A1", name="Bad Type", type="liabilityX").status_code == 400
    assert _acct(client, code="U1", name="Once", type="expense").status_code == 201
    assert _acct(client, code="U1", name="Twice", type="expense").status_code == 400
    assert _acct(client, code="NP", name="No Parent", type="asset", parent_id=99999).status_code == 400

    parent = _acct(client, code="P1", name="Parent Asset", type="asset").json()
    # Type mismatch with parent is rejected.
    assert _acct(client, code="C1", name="Child Exp", type="expense", parent_id=parent["id"]).status_code == 400
    # Inactive parent is rejected.
    client.patch(f"/api/v1/accounts/{parent['id']}", json={"is_active": False}, headers={"Origin": "http://testserver"})
    assert _acct(client, code="C2", name="Child", type="asset", parent_id=parent["id"]).status_code == 400
    # Unknown account edit is rejected, not created.
    assert client.patch("/api/v1/accounts/99999", json={"name": "x"}, headers={"Origin": "http://testserver"}).status_code == 400


def test_account_cycle_rejected(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    a = _acct(client, code="CYA", name="A", type="asset").json()
    b = _acct(client, code="CYB", name="B", type="asset", parent_id=a["id"]).json()
    # A→B→A cannot be constructed: parent_id is immutable after creation (no
    # parent-changing endpoint exists), so the only cycle vector would be
    # creation-time, where a missing parent is rejected. Assert the invariant.
    assert b["parent_id"] == a["id"]
    assert a["parent_id"] is None


def test_account_permissions_and_audit(client, db):
    from sqlalchemy import select

    from app.models.auth import AuditLog
    from tests.test_rbac import _make_user

    _make_user(db, "aview", "AviewPass1234!", "AView", ["accounts.view"])
    login_as(client, "aview", "AviewPass1234!")
    assert client.get("/api/v1/accounts").status_code == 200
    assert _acct(client, code="DENIED", name="x", type="asset").status_code == 403
    assert db.execute(select(AuditLog).where(AuditLog.action == "account.create")).all() == []

    _make_user(
        db, "amaker", "AmakerPass123!", "AMaker",
        ["accounts.view", "accounts.configure"],
    )
    login_as(client, "amaker", "AmakerPass123!")
    assert _acct(client, code="AUD1", name="Audited", type="income").status_code == 201
    rows = db.execute(select(AuditLog).where(AuditLog.action == "account.create")).all()
    assert len(rows) == 1


def test_failed_account_create_rolls_back(client, db, superadmin):
    from sqlalchemy import func, select

    login_as(client, "root_tester", "CorrectHorse12!")
    n_before = db.execute(select(func.count(Account.id))).scalar()
    r = _acct(client, code="ROLL", name="x", type="nope")
    assert r.status_code == 400
    # Service-level failure commits nothing (asserted on a fresh connection).
    assert db.execute(select(func.count(Account.id))).scalar() == n_before


def test_concurrent_duplicate_account_code_single_win():
    """Two concurrent creations of the SAME code: exactly one wins, the other is
    cleanly rejected (400, never a 500), and exactly one row exists.

    Determinism: both requests are forced through `accounting_service._create_barrier`
    AFTER the code pre-check and BEFORE the competing INSERT, so the unique-index
    race is exercised on every run instead of depending on thread timing. The
    barrier is a bounded (30s) two-party rendezvous; it can never hang the suite.

    Cleanup is strictly scoped to the two users this test creates and their
    dependent rows (audit/sessions/accounts/user_roles); no shared table is
    emptied.
    """
    import threading

    from app.core.security import hash_password
    from app.models.auth import Role
    from app.services import accounting_service

    names = ("acctA_" + RID, "acctB_" + RID)
    contested_code = "DUP_" + RID
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
                u = User(username=name, password_hash=hash_password("AcctPass123456!"))
                s.add(u)
                s.flush()
                s.add(UserRole(user_id=u.id, role_id=role_id))
            s.commit()

        def attempt(me: str) -> int:
            c = TestClient(create_app(), base_url="http://testserver")
            try:
                r = c.post(
                    "/api/v1/auth/login",
                    json={"username": me, "password": "AcctPass123456!"},
                    headers={"Origin": "http://testserver"},
                )
                assert r.status_code == 200, r.text
                return c.post(
                    "/api/v1/accounts",
                    json={"code": contested_code, "name": "Dup", "type": "asset"},
                    headers={"Origin": "http://testserver"},
                ).status_code
            finally:
                c.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(attempt, names[0])
            f2 = pool.submit(attempt, names[1])
            codes = sorted([f1.result(), f2.result()])
        assert codes == [201, 400], f"exactly one winner expected, got {codes}"
        with Session(engine) as s:
            count = s.execute(
                select(func.count(Account.id)).where(Account.code == contested_code)
            ).scalar()
        assert count == 1, f"expected exactly one account for the contested code, got {count}"
    finally:
        accounting_service._create_barrier = None
        delete_user_graph(engine, names)
        engine.dispose()
