"""Authentication, sessions, RBAC checks, and guarded user administration."""
import datetime as dt

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.core.security import hash_password, hash_token, new_session_token, verify_password
from app.models.auth import (
    Permission,
    Role,
    RolePermission,
    Session,
    User,
    UserRole,
    utcnow,
)
from app.services import audit_service

SUPER_ADMIN_ROLE = "Super Admin"


class AuthError(Exception):
    pass


class LockedError(AuthError):
    pass


class PermissionDenied(Exception):
    pass


def user_permissions(db: DbSession, user_id: int) -> set[str]:
    rows = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).all()
    return {r[0] for r in rows}


def require_permission(db: DbSession, user: User, code: str) -> None:
    if code not in user_permissions(db, user.id):
        raise PermissionDenied(code)


def _is_super_admin(db: DbSession, user_id: int) -> bool:
    return (
        db.execute(
            select(func.count())
            .select_from(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .where(and_(UserRole.user_id == user_id, Role.name == SUPER_ADMIN_ROLE))
        ).scalar()
        or 0
    ) > 0


def _membership_lock(db: DbSession) -> None:
    """Serialize Super-Admin membership changes across processes.

    The last-admin count check and the membership write must be atomic with
    respect to concurrent deactivations; otherwise two requests could each
    observe two active admins and both proceed. Transaction-scoped.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('scn_admin_membership'))"))


def count_active_super_admins(db: DbSession) -> int:
    return (
        db.execute(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(and_(User.is_active.is_(True), Role.name == SUPER_ADMIN_ROLE))
        ).scalar()
        or 0
    )


def authenticate(db: DbSession, username: str, password: str, ip: str | None) -> tuple[User, str]:
    settings = get_settings()
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    now = utcnow()
    if user is None or not user.is_active:
        raise AuthError("Invalid credentials.")
    if user.locked_until is not None and user.locked_until > now:
        raise LockedError("Account temporarily locked after failed logins.")
    if not verify_password(user.password_hash, password):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= settings.MAX_LOGIN_ATTEMPTS:
            user.locked_until = now + dt.timedelta(minutes=settings.LOCKOUT_MINUTES)
        db.add(user)
        db.commit()
        audit_service.log_event(
            db, actor_id=user.id, action="login.failed", entity="users", entity_id=user.id,
            details={"ip": ip},
        )
        db.commit()
        raise AuthError("Invalid credentials.")
    user.failed_logins = 0
    user.locked_until = None
    token, digest = new_session_token()
    db.add(
        Session(
            user_id=user.id,
            token_hash=digest,
            expires_at=now + dt.timedelta(minutes=settings.SESSION_EXPIRE_MINUTES),
            ip=ip,
        )
    )
    db.add(user)
    db.commit()
    audit_service.log_event(
        db, actor_id=user.id, action="login.success", entity="sessions", details={"ip": ip}
    )
    db.commit()
    return user, token


def validate_session(db: DbSession, token: str | None) -> User | None:
    if not token:
        return None
    digest = hash_token(token)
    sess = db.execute(select(Session).where(Session.token_hash == digest)).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or sess.expires_at <= utcnow():
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    return user


def logout(db: DbSession, token: str, actor_id: int | None) -> None:
    sess = db.execute(
        select(Session).where(Session.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if sess is not None and sess.revoked_at is None:
        sess.revoked_at = utcnow()
        db.add(sess)
        audit_service.log_event(
            db, actor_id=actor_id, action="logout", entity="sessions", entity_id=sess.id
        )
    db.commit()


def revoke_all_sessions(db: DbSession, user_id: int) -> None:
    for sess in db.execute(
        select(Session).where(
            and_(Session.user_id == user_id, Session.revoked_at.is_(None))
        )
    ).scalars():
        sess.revoked_at = utcnow()
        db.add(sess)
    db.flush()


def create_user(
    db: DbSession, *, actor: User, username: str, password: str, role_names: list[str]
) -> User:
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise AuthError("Username already exists.")
    if SUPER_ADMIN_ROLE in role_names:
        _membership_lock(db)
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    for name in role_names:
        role = db.execute(select(Role).where(Role.name == name)).scalar_one_or_none()
        if role is None:
            raise AuthError(f"Unknown role: {name}.")
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    audit_service.log_event(
        db, actor_id=actor.id, action="user.create", entity="users",
        entity_id=user.id, details={"username": username, "roles": role_names},
    )
    db.commit()
    db.refresh(user)
    return user


def deactivate_user(db: DbSession, *, actor: User, user_id: int) -> User:
    if actor.id == user_id:
        raise AuthError("You cannot deactivate your own account.")
    user = db.get(User, user_id)
    if user is None:
        raise AuthError("User not found.")
    _membership_lock(db)  # count check + deactivation + session revocation stay atomic
    if _is_super_admin(db, user_id) and count_active_super_admins(db) <= 1:
        raise AuthError("Cannot deactivate the last active Super Admin.")
    user.is_active = False
    revoke_all_sessions(db, user_id)
    db.add(user)
    db.flush()
    audit_service.log_event(
        db, actor_id=actor.id, action="user.deactivate", entity="users", entity_id=user_id
    )
    db.commit()
    db.refresh(user)
    return user
