"""Append-only audit log with tamper-evident hash chain.

Security model (stated honestly): the hash chain provides DETECTION of
rewrites (via verify_chain), not prevention. A database owner/superuser with
direct access can rewrite rows; that attack is outside the application threat
model and is detected by verification plus off-server backups. What this module
does guarantee: concurrent application writers cannot silently fork the chain.
"""
import hashlib
import json

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as DbSession

from app.models.auth import AuditLog, utcnow

GENESIS = "GENESIS"
AUDIT_LOCK_KEY = "scn_audit_log"


def _canonical(action: str, entity: str, entity_id: str | None, details: dict | None) -> str:
    payload = {"action": action, "entity": entity, "entity_id": entity_id, "details": details or {}}
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
    body = _canonical(action, entity, None if entity_id is None else str(entity_id), details)
    digest = hashlib.sha256((prev_hash + body).encode()).hexdigest()
    row = AuditLog(
        created_at=utcnow(),
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


def verify_chain(db: DbSession, limit: int = 10000) -> dict:
    """Recompute hashes; report the FIRST invalid row and scan completeness.

    Returns {"ok", "checked", "complete", "first_bad_id", "limit"} where
    complete=True means the whole table was scanned (checked == total rows),
    so callers can distinguish full verification from a bounded sample.
    A missing (deleted) row surfaces as a prev_hash mismatch on its successor.
    """
    total = db.execute(select(func.count(AuditLog.id))).scalar() or 0
    rows = db.execute(select(AuditLog).order_by(AuditLog.id).limit(limit)).scalars().all()
    prev_hash = GENESIS
    for row in rows:
        if row.prev_hash != prev_hash:
            return {
                "ok": False, "checked": len(rows), "complete": len(rows) == total,
                "first_bad_id": row.id, "limit": limit,
            }
        body = _canonical(row.action, row.entity, row.entity_id, row.details)
        if hashlib.sha256((prev_hash + body).encode()).hexdigest() != row.hash:
            return {
                "ok": False, "checked": len(rows), "complete": len(rows) == total,
                "first_bad_id": row.id, "limit": limit,
            }
        prev_hash = row.hash
    return {
        "ok": True, "checked": len(rows), "complete": len(rows) == total,
        "first_bad_id": None, "limit": limit,
    }
