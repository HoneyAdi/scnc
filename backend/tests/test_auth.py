"""Authentication: bootstrap, login success/failure, lockout, sessions, logout."""
from sqlalchemy import select

from app.models.auth import Session as DbSession, User
from tests.conftest import login_as


def test_setup_and_login_flow(client, db):
    from sqlalchemy import delete

    from app.models.auth import SystemSetting

    r = client.get("/api/v1/setup/status")
    assert r.status_code == 200
    assert r.json() == {"initialized": False}

    # Lifespan startup may already have issued (and committed) a setup token outside
    # this test's transaction; reset to a known fresh-install state first.
    db.execute(delete(SystemSetting))
    db.commit()

    from app.services import bootstrap

    token = bootstrap.ensure_setup_token(db)
    assert token is not None and len(token) >= 16

    r = client.post(
        "/api/v1/setup/admin",
        json={"token": token, "username": "first_admin", "password": "Str0ngPassw0rd!"},
    )
    assert r.status_code == 201, r.text

    r = client.get("/api/v1/setup/status")
    assert r.json() == {"initialized": True}

    # Token is single-use: setup endpoint now refuses everything.
    r = client.post(
        "/api/v1/setup/admin",
        json={"token": token, "username": "second", "password": "Str0ngPassw0rd!"},
    )
    assert r.status_code == 400

    # Login works and sets a session cookie; /me reflects the user + permissions.
    r = login_as(client, "first_admin", "Str0ngPassw0rd!")
    assert r.status_code == 200, r.text
    assert "scnc_session" in r.cookies
    body = r.json()
    assert body["user"]["username"] == "first_admin"
    assert "users.create" in body["user"]["permissions"]

    r = client.get("/api/v1/me")
    assert r.status_code == 200
    assert r.json()["username"] == "first_admin"

    # Logout revokes the session: the same cookie is then rejected.
    r = client.post("/api/v1/auth/logout", headers={"Origin": "http://testserver"})
    assert r.status_code == 200
    r = client.get("/api/v1/me")
    assert r.status_code == 401


def test_login_failure_and_lockout(client, superadmin, db):
    for _ in range(5):
        r = login_as(client, "root_tester", "wrong-password-1")
        assert r.status_code == 401
    # Account is now locked even with the correct password.
    r = login_as(client, "root_tester", "CorrectHorse12!")
    assert r.status_code == 423, r.text
    user = db.execute(select(User).where(User.username == "root_tester")).scalar_one()
    assert user.locked_until is not None


def test_unknown_user_rejected(client):
    r = login_as(client, "nobody-here", "whatever-password")
    assert r.status_code == 401


def test_session_token_stored_hashed(client, superadmin, db):
    r = login_as(client, "root_tester", "CorrectHorse12!")
    assert r.status_code == 200
    cookie = r.cookies["scnc_session"]
    rows = db.execute(select(DbSession.token_hash)).all()
    assert rows, "expected a session row"
    for (digest,) in rows:
        assert digest != cookie
        assert len(digest) == 64


def test_short_password_rejected_by_validation(client, db):
    from sqlalchemy import delete

    from app.models.auth import SystemSetting
    from app.services import bootstrap

    db.execute(delete(SystemSetting))
    db.commit()
    token = bootstrap.ensure_setup_token(db)
    r = client.post(
        "/api/v1/setup/admin",
        json={"token": token, "username": "shorty", "password": "too-short"},
    )
    assert r.status_code == 422
