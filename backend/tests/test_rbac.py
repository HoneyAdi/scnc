"""RBAC: backend enforcement (frontend hiding is never sufficient)."""
from sqlalchemy import select

from app.core.security import hash_password
from app.models.auth import Role, RolePermission, Permission, User, UserRole
from tests.conftest import login_as


def _make_user(db, username, password, role_name, codes=()):
    if role_name:
        role = db.execute(select(Role).where(Role.name == role_name)).scalar_one_or_none()
        if role is None:
            role = Role(name=role_name)
            db.add(role)
            db.flush()
            for code in codes:
                perm = db.execute(select(Permission).where(Permission.code == code)).scalar_one()
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
            db.flush()
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    if role_name:
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    return user


def test_unauthenticated_blocked(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/admin/users").status_code == 401
    assert client.get("/api/v1/admin/audit-log").status_code == 401


def test_forbidden_without_permission(client, db):
    _make_user(db, "viewer1", "ViewerPass123!", "Viewer", ["audit.view"])
    r = login_as(client, "viewer1", "ViewerPass123!")
    assert r.status_code == 200
    # Has audit.view but not users.create: direct API call must fail.
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "x", "password": "Xx1234567890!", "roles": []},
    )
    assert r.status_code == 403
    # But the permitted endpoint works.
    assert client.get("/api/v1/admin/audit-log").status_code == 200


def test_superadmin_user_lifecycle(client, superadmin):
    r = login_as(client, "root_tester", "CorrectHorse12!")
    assert r.status_code == 200

    r = client.post(
        "/api/v1/admin/users",
        json={"username": "clerk1", "password": "ClerkPass1234!", "roles": []},
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    r = client.get("/api/v1/admin/users")
    assert r.status_code == 200
    assert r.json()["total"] >= 2

    # Unknown role is rejected, not silently ignored.
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "clerk2", "password": "ClerkPass1234!", "roles": ["NoSuchRole"]},
    )
    assert r.status_code == 400

    # Creator cannot deactivate themselves.
    me = client.get("/api/v1/me").json()
    r = client.post(f"/api/v1/admin/users/{me['id']}/deactivate")
    assert r.status_code == 400

    # Deactivate the clerk; their sessions die immediately.
    r = client.post(f"/api/v1/admin/users/{uid}/deactivate")
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_last_super_admin_protected(client, superadmin, db):
    login_as(client, "root_tester", "CorrectHorse12!")
    me = client.get("/api/v1/me").json()
    # Only one active Super Admin exists: deactivation must be refused.
    r = client.post(f"/api/v1/admin/users/{me['id']}/deactivate")
    assert r.status_code == 400

    # With a second Super Admin present, deactivating one succeeds.
    second = User(username="root2", password_hash=hash_password("Root2Pass1234!"))
    db.add(second)
    db.flush()
    role_id = db.execute(select(Role.id).where(Role.name == "Super Admin")).scalar_one()
    db.add(UserRole(user_id=second.id, role_id=role_id))
    db.commit()
    # With a second Super Admin present, deactivating the OTHER admin succeeds.
    r = login_as(client, "root2", "Root2Pass1234!")
    assert r.status_code == 200
    r = client.post(f"/api/v1/admin/users/{me['id']}/deactivate")
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_deactivated_user_cannot_login(client, db, superadmin):
    _make_user(db, "temp1", "TempPass12345!", None)
    login_as(client, "root_tester", "CorrectHorse12!")
    target = db.execute(select(User).where(User.username == "temp1")).scalar_one()
    r = client.post(f"/api/v1/admin/users/{target.id}/deactivate")
    assert r.status_code == 200
    # Deactivated accounts cannot authenticate at all.
    r = login_as(client, "temp1", "TempPass12345!")
    assert r.status_code == 401


def test_live_session_dies_on_deactivation(client, db, superadmin):
    from sqlalchemy import select

    from app.models.auth import Session as DbSession
    from app.services import auth_service

    _make_user(db, "live1", "LivePass123456!", "Viewer", ["audit.view"])
    token = login_as(client, "live1", "LivePass123456!").json()["token"]
    assert auth_service.validate_session(db, token) is not None
    # Super Admin deactivates live1 (revokes all sessions in the same transaction).
    login_as(client, "root_tester", "CorrectHorse12!")
    target = db.execute(select(User).where(User.username == "live1")).scalar_one()
    assert client.post(f"/api/v1/admin/users/{target.id}/deactivate").status_code == 200
    # Every live1 session row is revoked, and the previously valid token no longer validates.
    remaining = db.execute(
        select(DbSession).where(
            DbSession.user_id == target.id, DbSession.revoked_at.is_(None)
        )
    ).all()
    assert remaining == []
    assert auth_service.validate_session(db, token) is None
