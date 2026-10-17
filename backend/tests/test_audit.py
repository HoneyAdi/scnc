"""Audit trail: events are written for relevant actions and the hash chain verifies."""
import os
import uuid

from app.services import audit_service
from tests.conftest import login_as

# Per-run unique suffix for real-commit usernames (see conftest scrub prefixes).
RID = f"{os.getpid()}{uuid.uuid4().hex[:6]}"


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
        s.execute(delete(User).where(User.username == "stress_actor_" + RID))
        s.commit()

    # Concurrent writers use their own committed connections, so the actor must
    # exist in COMMITTED state (the rollback-isolated fixture user is invisible
    # to them â€” which is exactly what the FK guard is supposed to enforce).
    setup_conn = app_engine.connect()
    try:
        with SaSession(bind=setup_conn) as s:
            _scrub(s)
            actor = User(username="stress_actor_" + RID, password_hash=hash_password("StressPass1234!"))
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
                s.execute(delete(User).where(User.username == "stress_actor_" + RID))
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


def test_tampering_any_covered_field_invalidates(client, db, superadmin):
    """Every immutable field in the format-2 payload is hash-covered."""
    import datetime as dt

    from sqlalchemy import select, update

    from app.models.auth import AuditLog

    audit_service.log_event(
        db, actor_id=superadmin.id, action="cov.one", entity="cov",
        entity_id="7", details={"k": "v"},
    )
    db.commit()
    row = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one()
    target_id = row.id
    tamperings = [
        ("action", {"action": "cov.FORGED"}),
        ("entity", {"entity": "forged"}),
        ("entity_id", {"entity_id": "forged"}),
        ("details", {"details": {"k": "FORGED"}}),
        ("prev_hash", {"prev_hash": "0" * 64}),
        ("created_at", {"created_at": dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)}),
    ]
    for label, tamper in tamperings:
        db.execute(update(AuditLog).where(AuditLog.id == target_id).values(**tamper))
        db.commit()
        report = audit_service.verify_chain(db)
        assert report["ok"] is False, label
        assert report["first_bad_id"] == target_id, label
        db.rollback()
    # actor_id tampering is stopped even earlier: the foreign key rejects a
    # non-existent actor outright (defense in depth alongside hashing).
    from sqlalchemy.exc import IntegrityError

    try:
        db.execute(update(AuditLog).where(AuditLog.id == target_id).values(actor_id=424242))
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        db.rollback()
        raise AssertionError("forged actor_id should violate the users FK")


def test_legacy_format_rows_still_verify(client, db, superadmin):
    """Pre-format-2 rows verify via the legacy payload and are counted, not failed."""
    import hashlib
    import json

    from sqlalchemy import select

    from app.models.auth import AuditLog
    from app.services.audit_service import GENESIS, _canonical_v1

    body = _canonical_v1("old.op", "old", "1", {"legacy": True})
    digest = hashlib.sha256((GENESIS + body).encode()).hexdigest()
    db.add(
        AuditLog(
            actor_id=superadmin.id, action="old.op", entity="old", entity_id="1",
            details={"legacy": True}, prev_hash=GENESIS, hash=digest,
        )
    )
    db.commit()
    audit_service.log_event(db, actor_id=superadmin.id, action="new.op", entity="new")
    db.commit()
    report = audit_service.verify_chain(db)
    assert report["ok"] is True, report
    assert report["complete"] is True
    assert report["legacy_format_count"] == 1


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


def test_tail_truncation_invisible_without_checkpoint(client, db, superadmin):
    """Documents the honest limitation: deleting the FINAL row leaves a
    shorter but internally consistent chain, which verifies ok=True."""
    from sqlalchemy import delete, select

    from app.models.auth import AuditLog

    audit_service.log_event(db, actor_id=superadmin.id, action="d.one", entity="t")
    audit_service.log_event(db, actor_id=superadmin.id, action="d.two", entity="t")
    db.commit()
    tip = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one()
    tip_hash, tip_id = tip.hash, tip.id
    db.execute(delete(AuditLog).where(AuditLog.id == tip_id))
    db.commit()
    # Chain alone cannot see the missing tail.
    assert audit_service.verify_chain(db)["ok"] is True
    # An external checkpoint (tip hash + max id) detects it precisely.
    anchored = audit_service.verify_chain(
        db, expected_tip_hash=tip_hash, expected_max_id=tip_id
    )
    assert anchored["ok"] is False
    assert anchored["tip_ok"] is False
    assert anchored["first_bad_id"] is None  # no internal break: links are intact
    # And a correct anchor passes.
    db.execute(delete(AuditLog))
    db.commit()
    audit_service.log_event(db, actor_id=superadmin.id, action="d.uno", entity="t")
    db.commit()
    now_tip = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one()
    good = audit_service.verify_chain(
        db, expected_tip_hash=now_tip.hash, expected_max_id=now_tip.id
    )
    assert good["ok"] is True
    assert good["tip_ok"] is True


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
