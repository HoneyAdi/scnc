"""Browser/session transport security: origin checks and the production TLS gate."""


def test_cross_origin_post_rejected(client, superadmin):
    from tests.conftest import login_as

    login_as(client, "root_tester", "CorrectHorse12!")
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "x", "password": "Xx1234567890!", "roles": []},
        headers={"Origin": "http://evil.test"},
    )
    assert r.status_code == 403
    # Referer is checked too when Origin is absent.
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "x", "password": "Xx1234567890!", "roles": []},
        headers={"Referer": "http://evil.test/stolen-form"},
    )
    assert r.status_code == 403


def test_same_origin_and_absent_origin_allowed(client, superadmin):
    from tests.conftest import login_as

    login_as(client, "root_tester", "CorrectHorse12!")
    # Same-origin browser POST passes.
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "ok1", "password": "OkPass1234567!", "roles": []},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 201, r.text
    # Non-browser clients (no Origin/Referer) still work; safe methods unaffected.
    assert client.get("/api/v1/me", headers={"Origin": "http://evil.test"}).status_code == 200


def test_prod_refuses_insecure_startup():
    from app.main import enforce_prod_security

    class Cfg:
        pass

    dev = Cfg()
    dev.ENV = "dev"
    dev.SESSION_SECURE_COOKIE = False
    enforce_prod_security(dev)  # localhost development stays usable

    prod_tls = Cfg()
    prod_tls.ENV = "prod"
    prod_tls.SESSION_SECURE_COOKIE = True
    enforce_prod_security(prod_tls)

    prod_plain = Cfg()
    prod_plain.ENV = "prod"
    prod_plain.SESSION_SECURE_COOKIE = False
    try:
        enforce_prod_security(prod_plain)
    except RuntimeError:
        pass
    else:
        raise AssertionError("prod without Secure cookies must refuse to start")
