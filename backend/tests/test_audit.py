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

    report = audit_service.verify_chain(db)
    assert report["ok"] is True
    assert report["complete"] is True
    assert report["checked"] >= 2
    assert report["first_bad_id"] is None


def test_concurrent_audit_appends_keep_single_chain(client, db, superadmin, app_engine):
    import threading

    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session as SaSession

    from app.core.security import hash_password
    from app.db.session import get_engine
    from app.models.auth import AuditLog, User

    def _scrub(s):
        # Idempotent pre/post cleanup: a previously crashed run must not pollute this one.
        from sqlalchemy import delete

        s.execute(delete(AuditLog).where(AuditLog.action.like("stress.%")))
        s.execute(delete(User).where(User.username == "stress_actor"))
        s.commit()

    # Concurrent writers use their own committed connections, so the actor must
    # exist in COMMITTED state (the rollback-isolated fixture user is invisible
    # to them — which is exactly what the FK guard is supposed to enforce).
    setup_conn = app_engine.connect()
    try:
        with SaSession(bind=setup_conn) as s:
            _scrub(s)
            actor = User(username="stress_actor", password_hash=hash_password("StressPass1234!"))
            s.add(actor)
            s.commit()
            actor_id = actor.id
    finally:
        setup_conn.close()

    engine = get_engine()
    errors: list = []

    def write(i: int):
        try:
            conn = engine.connect()
            try:
                from sqlalchemy.orm import Session as SaSession2

                s = SaSession2(bind=conn)
                try:
                    audit_service.log_event(
                        s, actor_id=actor_id, action=f"stress.{i}",
                        entity="stress", entity_id=str(i),
                    )
                    s.commit()
                finally:
                    s.close()
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - collected, then asserted empty
            errors.append(exc)

    try:
        threads = [threading.Thread(target=write, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        # Verify on a fresh connection: all 12 events present, one linear chain.
        check_conn = engine.connect()
        try:
            with SaSession(bind=check_conn) as s:
                report = audit_service.verify_chain(s)
        finally:
            check_conn.close()
        assert report["ok"] is True, report
        assert report["complete"] is True
        assert report["checked"] >= 12
    finally:
        cleanup = app_engine.connect()
        try:
            with SaSession(bind=cleanup) as s:
                s.execute(delete(AuditLog).where(AuditLog.action.like("stress.%")))
                s.execute(delete(User).where(User.username == "stress_actor"))
                s.commit()
        finally:
            cleanup.close()


def test_tampered_record_reports_first_bad_id(client, db, superadmin):
    from sqlalchemy import update

    from app.models.auth import AuditLog

    audit_service.log_event(db, actor_id=superadmin.id, action="a.one", entity="t")
    audit_service.log_event(db, actor_id=superadmin.id, action="a.two", entity="t")
    db.commit()
    victim = db.execute(
        __import__("sqlalchemy").select(AuditLog).order_by(AuditLog.id).limit(1)
    ).scalar_one()
    db.execute(
        update(AuditLog).where(AuditLog.id == victim.id).values(details={"forged": True})
    )
    db.commit()
    report = audit_service.verify_chain(db)
    assert report["ok"] is False
    assert report["first_bad_id"] == victim.id


def test_deleted_record_breaks_successor_link(client, db, superadmin):
    from sqlalchemy import delete, select

    from app.models.auth import AuditLog

    audit_service.log_event(db, actor_id=superadmin.id, action="b.one", entity="t")
    audit_service.log_event(db, actor_id=superadmin.id, action="b.two", entity="t")
    audit_service.log_event(db, actor_id=superadmin.id, action="b.three", entity="t")
    db.commit()
    ids = [r.id for r in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars()]
    assert len(ids) == 3
    db.execute(delete(AuditLog).where(AuditLog.id == ids[1]))
    db.commit()
    report = audit_service.verify_chain(db)
    assert report["ok"] is False
    assert report["first_bad_id"] == ids[2]


def test_limited_scan_reports_incomplete(client, db, superadmin):
    audit_service.log_event(db, actor_id=superadmin.id, action="c.one", entity="t")
    audit_service.log_event(db, actor_id=superadmin.id, action="c.two", entity="t")
    db.commit()
    report = audit_service.verify_chain(db, limit=1)
    assert report["ok"] is True
    assert report["checked"] == 1
    assert report["complete"] is False
    full = audit_service.verify_chain(db)
    assert full["complete"] is True


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
