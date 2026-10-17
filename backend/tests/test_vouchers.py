"""Draft voucher + journal-line foundation: validation, atomicity, RBAC, audit.

Everything here exercises DRAFT behaviour only. No posting/approval/reversal
path exists, and none is tested as if it did. Tests use the rolled-back `db`
transaction fixture, so nothing needs cleanup and no table is ever emptied.
"""
import uuid

from sqlalchemy import func, select

from app.models.accounting import NumberSequence, Voucher, VoucherLine
from app.models.auth import AuditLog
from tests.conftest import login_as
from tests.test_rbac import _make_user

RID = uuid.uuid4().hex[:8]
ORIGIN = {"Origin": "http://testserver"}


def _period(client, code, starts, ends):
    r = client.post(
        "/api/v1/periods",
        json={"code": code, "name": code, "starts_on": starts, "ends_on": ends},
        headers=ORIGIN,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _acct(client, code, name, type):
    r = client.post(
        "/api/v1/accounts",
        json={"code": code, "name": name, "type": type},
        headers=ORIGIN,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _setup(client):
    period = _period(client, "VFY_" + RID, "2026-04-01", "2027-03-31")
    cash = _acct(client, "VCA_" + RID, "Cash", "asset")
    income = _acct(client, "VIN_" + RID, "Fees", "income")
    return period, cash, income


def _create(client, fy_id, lines, vtype="journal", date="2026-04-05", narration=""):
    return client.post(
        "/api/v1/vouchers",
        json={
            "voucher_type": vtype, "fy_id": fy_id, "voucher_date": date,
            "narration": narration, "lines": lines,
        },
        headers=ORIGIN,
    )


def test_voucher_create_draft_and_get(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, income = _setup(client)
    created = _create(
        client, period["id"],
        [
            {"account_id": cash["id"], "debit": "100.00", "credit": "0.00"},
            {"account_id": income["id"], "debit": "0.00", "credit": "100.00"},
        ],
        narration="draft test",
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    assert body["number"].startswith("JV-")
    assert body["version"] == 1

    detail = client.get(f"/api/v1/vouchers/{body['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["narration"] == "draft test"
    assert len(payload["lines"]) == 2
    assert sorted(line["debit"] for line in payload["lines"]) == ["0.00", "100.00"]
    assert all(isinstance(line["debit"], str) for line in payload["lines"])


def test_voucher_unbalanced_and_single_line_drafts_allowed(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    # Unbalanced 2-line draft: allowed. Balance is a POSTING-time rule.
    unbalanced = _create(
        client, period["id"],
        [
            {"account_id": cash["id"], "debit": "100.00", "credit": "0.00"},
            {"account_id": cash["id"], "debit": "0.00", "credit": "40.00"},
        ],
    )
    assert unbalanced.status_code == 201, unbalanced.text
    assert unbalanced.json()["status"] == "draft"
    # Single-line draft: also allowed.
    single = _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "10.00", "credit": "0.00"}],
    )
    assert single.status_code == 201, single.text
    assert single.json()["status"] == "draft"


def test_voucher_requires_authentication(client):
    assert client.get("/api/v1/vouchers").status_code == 401
    assert client.post("/api/v1/vouchers", json={}, headers=ORIGIN).status_code == 401


def test_voucher_permission_enforced(client, db):
    _make_user(db, "vv_" + RID, "VvPass123456!", "VV", ["vouchers.view"])
    login_as(client, "vv_" + RID, "VvPass123456!")
    assert client.get("/api/v1/vouchers").status_code == 200
    r = client.post(
        "/api/v1/vouchers",
        json={"voucher_type": "journal", "fy_id": 1, "voucher_date": "2026-04-05", "lines": []},
        headers=ORIGIN,
    )
    assert r.status_code == 403
    assert db.execute(select(AuditLog).where(AuditLog.action == "voucher.create")).all() == []


def test_voucher_create_only_user_cannot_list(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    _make_user(db, "vc_" + RID, "VcPass123456!", "VCREATE", ["vouchers.create"])
    login_as(client, "vc_" + RID, "VcPass123456!")
    r = _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "5.00", "credit": "0.00"}],
    )
    assert r.status_code == 201, r.text
    assert client.get("/api/v1/vouchers").status_code == 403


def test_voucher_invalid_type_rejected(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    r = _create(client, 999999, [{"account_id": 1, "debit": "1.00", "credit": "0.00"}], vtype="bogus")
    assert r.status_code == 400
    assert "type" in r.json()["detail"].lower()


def test_voucher_unknown_period(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    r = _create(
        client, 999999,
        [{"account_id": cash["id"], "debit": "1.00", "credit": "0.00"}],
    )
    assert r.status_code == 400


def test_voucher_date_outside_period(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    r = _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "1.00", "credit": "0.00"}],
        date="2020-01-01",
    )
    assert r.status_code == 400


def test_voucher_closed_period_rejected(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    assert client.post(f"/api/v1/periods/{period['id']}/close", headers=ORIGIN).status_code == 200
    r = _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "1.00", "credit": "0.00"}],
    )
    assert r.status_code == 400


def test_voucher_inactive_and_unknown_account_rejected(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, income = _setup(client)
    assert client.patch(
        f"/api/v1/accounts/{income['id']}", json={"is_active": False}, headers=ORIGIN
    ).status_code == 200
    assert _create(
        client, period["id"],
        [{"account_id": income["id"], "debit": "1.00", "credit": "0.00"}],
    ).status_code == 400
    assert _create(
        client, period["id"],
        [{"account_id": 999999, "debit": "1.00", "credit": "0.00"}],
    ).status_code == 400


def test_voucher_line_must_have_exactly_one_positive_side(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    both = _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "5.00", "credit": "5.00"}],
    )
    assert both.status_code == 400
    neither = _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "0.00", "credit": "0.00"}],
    )
    assert neither.status_code == 400


def test_voucher_rejects_negative_and_imprecise_amounts(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    assert _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "-1.00", "credit": "0.00"}],
    ).status_code == 400
    assert _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "1.005", "credit": "0.00"}],
    ).status_code == 400


def test_voucher_requires_at_least_one_line(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, _, _ = _setup(client)
    assert _create(client, period["id"], []).status_code == 400


def test_voucher_create_is_audited(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, income = _setup(client)
    r = _create(
        client, period["id"],
        [
            {"account_id": cash["id"], "debit": "100.00", "credit": "0.00"},
            {"account_id": income["id"], "debit": "0.00", "credit": "100.00"},
        ],
    )
    assert r.status_code == 201, r.text
    rows = db.execute(select(AuditLog).where(AuditLog.action == "voucher.create")).scalars().all()
    assert len(rows) == 1
    assert rows[0].entity == "vouchers"
    assert rows[0].details["number"] == r.json()["number"]


def test_voucher_invalid_line_leaves_no_partial_rows(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    assert db.execute(select(func.count(Voucher.id))).scalar() == 0
    r = _create(
        client, period["id"],
        [
            {"account_id": cash["id"], "debit": "1.00", "credit": "0.00"},
            {"account_id": 999999, "debit": "1.00", "credit": "0.00"},
        ],
    )
    assert r.status_code == 400
    assert db.execute(select(func.count(Voucher.id))).scalar() == 0
    assert db.execute(select(func.count(VoucherLine.id))).scalar() == 0
    assert db.execute(select(func.count(NumberSequence.id))).scalar() == 0


def test_voucher_audit_failure_rolls_back_everything(db, superadmin, app_engine, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session as SaSession

    from app.api.deps import get_db
    from app.main import create_app
    from app.services import audit_service

    def committed():
        conn = app_engine.connect()
        try:
            with SaSession(bind=conn) as s:
                return (
                    s.execute(select(func.count(Voucher.id))).scalar(),
                    s.execute(select(func.count(VoucherLine.id))).scalar(),
                    s.execute(select(func.count(NumberSequence.id))).scalar(),
                    s.execute(select(func.count(AuditLog.id)).where(AuditLog.action == "voucher.create")).scalar(),
                )
        finally:
            conn.close()

    quiet = TestClient(create_app(), base_url="http://testserver", raise_server_exceptions=False)
    quiet.app.dependency_overrides[get_db] = lambda: db
    try:
        login_as(quiet, "root_tester", "CorrectHorse12!")
        period, cash, income = _setup(quiet)
        before = committed()

        def boom(*args, **kwargs):
            raise RuntimeError("audit store unavailable")

        monkeypatch.setattr(audit_service, "log_event", boom)
        r = quiet.post(
            "/api/v1/vouchers",
            json={
                "voucher_type": "journal", "fy_id": period["id"], "voucher_date": "2026-04-05",
                "lines": [
                    {"account_id": cash["id"], "debit": "10.00", "credit": "0.00"},
                    {"account_id": income["id"], "debit": "0.00", "credit": "10.00"},
                ],
            },
            headers=ORIGIN,
        )
        assert r.status_code == 500
        db.rollback()
        assert committed() == before
    finally:
        quiet.close(), "no header, line, number, or audit row may persist"


def test_voucher_numbering_is_sequential_and_scoped(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, income = _setup(client)
    lines = [{"account_id": cash["id"], "debit": "1.00", "credit": "0.00"}]
    first = _create(client, period["id"], lines)
    second = _create(client, period["id"], lines)
    assert first.json()["number"] == "JV-00001"
    assert second.json()["number"] == "JV-00002"
    receipt = _create(client, period["id"], lines, vtype="receipt")
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["number"] == "RV-00001"


def test_voucher_no_mutating_or_posting_endpoints(client, db, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    created = _create(
        client, period["id"],
        [{"account_id": cash["id"], "debit": "5.00", "credit": "0.00"}],
    )
    vid = created.json()["id"]
    assert client.put(f"/api/v1/vouchers/{vid}", json={}, headers=ORIGIN).status_code in (404, 405)
    assert client.patch(f"/api/v1/vouchers/{vid}", json={}, headers=ORIGIN).status_code in (404, 405)
    assert client.delete(f"/api/v1/vouchers/{vid}", headers=ORIGIN).status_code in (404, 405)
    # No posting/approval path exists; the voucher must remain a draft.
    assert client.post(f"/api/v1/vouchers/{vid}/post", headers=ORIGIN).status_code in (404, 405)
    assert client.get(f"/api/v1/vouchers/{vid}").json()["status"] == "draft"


def test_voucher_list_pagination(client, superadmin):
    login_as(client, "root_tester", "CorrectHorse12!")
    period, cash, _ = _setup(client)
    for _ in range(3):
        assert _create(
            client, period["id"],
            [{"account_id": cash["id"], "debit": "1.00", "credit": "0.00"}],
        ).status_code == 201
    page = client.get("/api/v1/vouchers?limit=2&offset=0").json()
    assert page["total"] >= 3
    assert len(page["items"]) == 2
