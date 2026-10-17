"""Append-only audit log with tamper-evident hash chain.

Security model (stated honestly): the hash chain provides DETECTION of
rewrites (via verify_chain), not prevention. A database owner/superuser with
direct access can rewrite rows; that attack is outside the application threat
model and is detected by verification plus off-server backups — EXCEPT a tail
truncation with no external reference, which the chain alone cannot see (see
verify_chain's expected_tip_* parameters and the checkpoint design note in
TESTING.md). What this module
does guarantee: concurrent application writers cannot silently fork the chain.
"""
import datetime as dt
import hashlib
import json

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as DbSession

from app.models.auth import AuditLog, utcnow

GENESIS = "GENESIS"
AUDIT_LOCK_KEY = "scn_audit_log"
HASH_FORMAT_VERSION = 2


def _ts(moment: dt.datetime) -> str:
    """Deterministic timestamp representation: always UTC.

    PostgreSQL returns timestamptz in the SESSION timezone, so the same instant
    formats differently across connections. Canonicalizing to UTC keeps the
    hashed bytes identical at write and verify time on any server timezone.
    """
    return moment.astimezone(dt.timezone.utc).isoformat()


def _canonical_v1(action: str, entity: str, entity_id: str | None, details: dict | None) -> str:
    """Legacy payload (format 1): kept ONLY for verifying pre-existing rows."""
    payload = {"action": action, "entity": entity, "entity_id": entity_id, "details": details or {}}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _canonical(
    action: str,
    entity: str,
    entity_id: str | None,
    details: dict | None,
    actor_id: int | None,
    created_at: str,
) -> str:
    """Current payload (format 2): every immutable field is covered.

    created_at must be the EXACT stored ISO-8601 timestamp (UTC, tz-aware);
    pass row.created_at.isoformat() when verifying stored rows.
    """
    payload = {
        "action": action,
        "actor_id": actor_id,
        "created_at": created_at,
        "entity": entity,
        "entity_id": entity_id,
        "details": details or {},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def log_event(
    db: DbSession,
    *,
    actor_id: int | None,
    action: str,
    entity: str,
    entity_id: str | int | None = None,
    details: dict | None = None,
) -> AuditLog:
    # Serialize chain appends across processes: the advisory lock is
    # transaction-scoped, so (read-max-id, insert) is atomic with respect to
    # other application writers. No branch can form silently.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": AUDIT_LOCK_KEY})
    prev = db.execute(select(func.max(AuditLog.id))).scalar()
    prev_hash = GENESIS
    if prev is not None:
        last = db.get(AuditLog, prev)
        prev_hash = last.hash if last else GENESIS
    now = utcnow()
    body = _canonical(
        action,
        entity,
        None if entity_id is None else str(entity_id),
        details,
        actor_id,
        _ts(now),
    )
    digest = hashlib.sha256((prev_hash + body).encode()).hexdigest()
    row = AuditLog(
        created_at=now,
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=None if entity_id is None else str(entity_id),
        details=details,
        prev_hash=prev_hash,
        hash=digest,
    )
    db.add(row)
    db.flush()
    return row


def verify_chain(
    db: DbSession,
    limit: int = 10000,
    expected_tip_hash: str | None = None,
    expected_max_id: int | None = None,
) -> dict:
    """Recompute hashes; report the FIRST invalid row and scan completeness.

    Returns {"ok", "checked", "complete", "first_bad_id", "legacy_format_count",
    "tip_ok", "limit"}. Format handling (safe, explicit transition, no history
    rewrite): each row is first checked against the current format-2 payload;
    rows written before format 2 are then checked against the legacy format-1
    payload and counted in legacy_format_count instead of failing.
    A missing (deleted) MIDDLE row surfaces as a prev_hash mismatch on its
    successor. A deleted TAIL is invisible to the chain alone — pass
    expected_tip_hash / expected_max_id from an external checkpoint to detect
    it (tip_ok=False with first_bad_id=None means exactly that: internally
    consistent, but anchored tip disagrees). Without an external reference,
    tail truncation cannot be distinguished from a quiet system; see the
    checkpoint design note in TESTING.md.
    """
    total = db.execute(select(func.count(AuditLog.id))).scalar() or 0
    rows = db.execute(select(AuditLog).order_by(AuditLog.id).limit(limit)).scalars().all()
    prev_hash = GENESIS
    legacy = 0
    for row in rows:
        if row.prev_hash != prev_hash:
            return {
                "ok": False, "checked": len(rows), "complete": len(rows) == total,
                "first_bad_id": row.id, "legacy_format_count": legacy,
                "tip_ok": None, "limit": limit,
            }
        current = _canonical(
            row.action, row.entity, row.entity_id, row.details,
            row.actor_id, _ts(row.created_at),
        )
        if hashlib.sha256((prev_hash + current).encode()).hexdigest() == row.hash:
            prev_hash = row.hash
            continue
        legacy_body = _canonical_v1(row.action, row.entity, row.entity_id, row.details)
        if hashlib.sha256((prev_hash + legacy_body).encode()).hexdigest() == row.hash:
            legacy += 1
            prev_hash = row.hash
            continue
        return {
            "ok": False, "checked": len(rows), "complete": len(rows) == total,
            "first_bad_id": row.id, "legacy_format_count": legacy,
            "tip_ok": None, "limit": limit,
        }
    tip_ok: bool | None = None
    ok = True
    if expected_tip_hash is not None or expected_max_id is not None:
        tip_ok = True
        tip_hash = rows[-1].hash if rows else GENESIS
        tip_id = rows[-1].id if rows else 0
        if expected_tip_hash is not None and tip_hash != expected_tip_hash:
            tip_ok = False
        if expected_max_id is not None and tip_id != expected_max_id:
            tip_ok = False
        ok = tip_ok
    return {
        "ok": ok, "checked": len(rows), "complete": len(rows) == total,
        "first_bad_id": None, "legacy_format_count": legacy,
        "tip_ok": tip_ok, "limit": limit,
    }
