"""User administration (permission-gated, audited, last-admin protected)."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.api import deps, schemas
from app.models.auth import Role, RolePermission, User, UserRole
from app.services import auth_service

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


def _out(db: DbSession, user: User) -> schemas.UserOut:
    role_names = [
        r[0]
        for r in db.execute(
            select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(
                UserRole.user_id == user.id
            )
        ).all()
    ]
    return schemas.UserOut(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        permissions=sorted(auth_service.user_permissions(db, user.id)),
    )


@router.get("", dependencies=[Depends(deps.require_permission("users.view"))])
def list_users(
    db: DbSession = Depends(deps.get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = db.execute(select(func.count(User.id))).scalar() or 0
    users = db.execute(select(User).order_by(User.id).limit(limit).offset(offset)).scalars().all()
    return {"total": total, "items": [_out(db, u) for u in users]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.CreateUserRequest,
    db: DbSession = Depends(deps.get_db),
    actor: User = Depends(deps.require_permission("users.create")),
):
    try:
        user = auth_service.create_user(
            db, actor=actor, username=payload.username,
            password=payload.password, role_names=payload.roles,
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _out(db, user)


@router.post("/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    db: DbSession = Depends(deps.get_db),
    actor: User = Depends(deps.require_permission("users.deactivate")),
):
    try:
        user = auth_service.deactivate_user(db, actor=actor, user_id=user_id)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _out(db, user)
