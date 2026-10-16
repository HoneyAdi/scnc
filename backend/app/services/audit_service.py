"""Append-only audit log with tamper-evident hash chain (detection, not prevention)."""
import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models.auth import AuditLog, utcnow

GENESIS = "GENESIS"


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


def verify_chain(db: DbSession, limit: int = 10000) -> tuple[bool, int]:
    """Recompute hashes; return (ok, checked_count). Detection control for privileged tampering."""
    rows = db.execute(select(AuditLog).order_by(AuditLog.id).limit(limit)).scalars().all()
    prev_hash = GENESIS
    for row in rows:
        if row.prev_hash != prev_hash:
            return False, row.id
        body = _canonical(row.action, row.entity, row.entity_id, row.details)
        if hashlib.sha256((prev_hash + body).encode()).hexdigest() != row.hash:
            return False, row.id
        prev_hash = row.hash
    return True, len(rows)
