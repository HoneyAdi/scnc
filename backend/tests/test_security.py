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


def test_origin_matrix(client, superadmin):
    """Scheme, host, and effective port are all compared — hostname alone is
    never sufficient. TestClient speaks http://testserver (effective port 80)."""
    from tests.conftest import login_as

    login_as(client, "root_tester", "CorrectHorse12!")
    payload = {"username": "uum", "password": "UumPass123456!", "roles": []}

    def post_as(headers):
        return client.post("/api/v1/admin/users", json=payload, headers=headers)

    # Different scheme, same host: rejected.
    assert post_as({"Origin": "https://testserver"}).status_code == 403
    # Different port, same scheme+host: rejected.
    assert post_as({"Origin": "http://testserver:9999"}).status_code == 403
    # Different host: rejected.
    assert post_as({"Origin": "http://other.test"}).status_code == 403
    # Explicit default port matching the effective port: allowed (same origin).
    assert post_as({"Origin": "http://testserver:80"}).status_code in (201, 400)
    # Malformed Origin present: fail closed.
    assert post_as({"Origin": "not-a-url###"}).status_code == 403
    assert post_as({"Origin": "ftp://testserver/x"}).status_code == 403
    # Allowed deployment origin from CORS_ORIGINS with correct triple: allowed.
    assert post_as({"Origin": "http://localhost:5173"}).status_code in (201, 400)
    # Same triple via Referer (no Origin): allowed.
    assert post_as({"Referer": "http://testserver/some/page"}).status_code in (201, 400)


def test_same_origin_and_absent_origin_allowed(client, superadmin):
    from tests.conftest import login_as

    login_as(client, "root_tester", "CorrectHorse12!")
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "ok1", "password": "OkPass1234567!", "roles": []},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 201, r.text
    assert client.get("/api/v1/me", headers={"Origin": "http://evil.test"}).status_code == 200


def test_cookie_auth_missing_origin_rejected(client, superadmin):
    from tests.conftest import login_as

    login_as(client, "root_tester", "CorrectHorse12!")
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "noorig", "password": "NoOrigPass123!", "roles": []},
    )
    assert r.status_code == 403


def test_bearer_auth_missing_origin_allowed(client, db, superadmin):
    from tests.conftest import login_as

    login_as(client, "root_tester", "CorrectHorse12!")
    token = client.cookies.get("scnc_session")
    client.cookies.clear()
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "bearertest", "password": "BearerPass123!", "roles": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_malformed_origin_with_cookie_rejected(client, superadmin):
    from tests.conftest import login_as

    login_as(client, "root_tester", "CorrectHorse12!")
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "malformed", "password": "MalformedPass1!", "roles": []},
        headers={"Origin": "not-a-url###"},
    )
    assert r.status_code == 403


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
