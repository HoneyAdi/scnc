"""Audit trail: events are written for relevant actions and the hash chain verifies."""
from app.services import audit_service
from tests.conftest import login_as


def test_audit_events_and_chain(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    client.post(
        "/api/v1/admin/users",
        json={"username": "audited1", "password": "AuditedPass12!", "roles": []},
    )
    r = client.get("/api/v1/admin/audit-log")
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()["items"]]
    assert "login.success" in actions
    assert "user.create" in actions

    ok, count = audit_service.verify_chain(db)
    assert ok is True
    assert count >= 2


def test_audit_view_requires_permission(client, db):
    from tests.test_rbac import _make_user

    _make_user(db, "noperm", "NopermPass123!", None)
    login_as(client, "noperm", "NopermPass123!")
    assert client.get("/api/v1/admin/audit-log").status_code == 403


def test_password_hashing_is_argon2id():
    from app.core import security

    h = security.hash_password("AnotherStr0ngPwd!")
    assert h.startswith("$argon2id$")
    assert security.verify_password(h, "AnotherStr0ngPwd!") is True
    assert security.verify_password(h, "wrong") is False
    try:
        security.hash_password("short")
    except ValueError:
        pass
    else:
        raise AssertionError("short password must be rejected")
