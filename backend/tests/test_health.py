"""Health checks: app liveness and database reachability."""


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_db_ok(client):
    r = client.get("/health/db")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok", "database": "reachable"}
