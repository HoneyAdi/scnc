"""First-Super-Admin bootstrap: one-time token, single use, expiring. No default creds."""
import datetime as dt
import secrets

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.core.security import hash_password, hash_token
from app.models.auth import Permission, Role, RolePermission, User, UserRole, utcnow
from app.services import audit_service
from app.services.auth_service import SUPER_ADMIN_ROLE

SETUP_TOKEN_HASH_KEY = "first_setup_token_hash"
SETUP_TOKEN_EXPIRY_KEY = "first_setup_expires_at"

SETUP_TOKEN_TTL_MINUTES = 120
SETUP_TOKEN_FILE = "setup_token.txt"


def write_setup_token_file(token: str) -> str:
    """Write the one-time token to a restricted local file (never logs, never commits).

    Returns the file path. Callers must log only the path, never the token value
    (the logging filter redacts token values by design).
    """
    import os

    from app.core.config import get_settings

    root = os.path.join(get_settings().STORAGE_ROOT, "setup")
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, SETUP_TOKEN_FILE)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode())
    finally:
        os.close(fd)
    return os.path.abspath(path)


def _get_setting(db: DbSession, key: str):
    from app.models.auth import SystemSetting

    row = db.get(SystemSetting, key)
    return row.value if row else None


def _set_setting(db: DbSession, key: str, value: dict) -> None:
    from app.models.auth import SystemSetting

    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def is_initialized(db: DbSession) -> bool:
    return db.execute(select(User.id).limit(1)).scalar_one_or_none() is not None


def ensure_setup_token(db: DbSession) -> str | None:
    """Create (once) and return the plaintext setup token, or None if already initialized.

    The plaintext is returned ONLY here so the server startup log can show it once.
    Only the hash is persisted.
    """
    from app.models.auth import SystemSetting

    if is_initialized(db):
        return None
    existing = db.get(SystemSetting, SETUP_TOKEN_HASH_KEY)
    if existing is not None:
        return None  # token already issued; check logs or re-run rotation via CLI later
    token = secrets.token_urlsafe(32)
    expiry = utcnow() + dt.timedelta(minutes=SETUP_TOKEN_TTL_MINUTES)
    db.add(SystemSetting(key=SETUP_TOKEN_HASH_KEY, value={"hash": hash_token(token)}))
    db.add(SystemSetting(key=SETUP_TOKEN_EXPIRY_KEY, value={"at": expiry.isoformat()}))
    try:
        db.commit()
    except IntegrityError:
        # Lost a concurrent issuance race: the other transaction won. Never
        # return a token we did not persist.
        db.rollback()
        return None
    return token


def consume_setup_token(db: DbSession, *, token: str, username: str, password: str) -> User:
    from app.models.auth import SystemSetting

    # Serialize concurrent setup attempts across processes: the advisory lock is
    # transaction-scoped, so exactly one claimant proceeds; the other blocks, then
    # re-checks and fails safely on the already-initialized system.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('scn_first_setup'))"))
    if is_initialized(db):
        raise ValueError("System is already initialized.")
    stored = db.get(SystemSetting, SETUP_TOKEN_HASH_KEY)
    expiry = db.get(SystemSetting, SETUP_TOKEN_EXPIRY_KEY)
    if stored is None or expiry is None:
        raise ValueError("Setup is not available.")
    if utcnow() > dt.datetime.fromisoformat(expiry.value["at"]):
        raise ValueError("Setup token has expired.")
    if hash_token(token) != stored.value.get("hash"):
        raise ValueError("Invalid setup token.")
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise ValueError("Username already exists.")
    role = db.execute(select(Role).where(Role.name == SUPER_ADMIN_ROLE)).scalar_one_or_none()
    if role is None:
        raise ValueError("Super Admin role is not seeded.")
    # Policy: the token is consumed ONLY by a fully successful setup. Any failure
    # above aborts before mutation, so a failed attempt leaves no partial admin
    # and the token remains valid for a legitimate retry.
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.delete(stored)
    db.delete(expiry)
    db.flush()
    audit_service.log_event(
        db, actor_id=user.id, action="setup.complete", entity="users",
        entity_id=user.id, details={"username": username},
    )
    db.commit()
    db.refresh(user)
    return user


def all_permission_codes() -> list[tuple[str, str, str]]:
    mods_actions = [
        ("users", ["view", "create", "edit", "deactivate"]),
        ("roles", ["view", "administer"]),
        ("audit", ["view"]),
        ("settings", ["view"]),
    ]
    return [(f"{m}.{a}", m, a) for m, acts in mods_actions for a in acts]


def seed_roles_permissions(db: DbSession) -> None:
    """Idempotent seed: permission codes + Super Admin role holding all of them. No users."""
    codes = all_permission_codes()
    existing = {r[0] for r in db.execute(select(Permission.code)).all()}
    for code, module, action in codes:
        if code not in existing:
            db.add(Permission(code=code, module=module, action=action))
    db.flush()
    role = db.execute(select(Role).where(Role.name == SUPER_ADMIN_ROLE)).scalar_one_or_none()
    if role is None:
        role = Role(name=SUPER_ADMIN_ROLE, is_system=True, description="Full administration")
        db.add(role)
        db.flush()
    perm_ids = {r.id for r in db.execute(select(Permission)).scalars()}
    have = {
        r[0]
        for r in db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
        ).all()
    }
    for pid in perm_ids - have:
        db.add(RolePermission(role_id=role.id, permission_id=pid))
    db.commit()
