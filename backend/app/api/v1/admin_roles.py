"""Role administration (permission-gated, audited)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api import deps, schemas
from app.models.auth import Permission, Role, RolePermission
from app.services import audit_service, auth_service
from app.models.auth import User

router = APIRouter(prefix="/admin/roles", tags=["admin-roles"])


def _out(db: DbSession, role: Role) -> schemas.RoleOut:
    codes = [
        r[0]
        for r in db.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        ).all()
    ]
    return schemas.RoleOut(
        id=role.id, name=role.name, is_system=role.is_system,
        description=role.description, permissions=sorted(codes),
    )


@router.get("", dependencies=[Depends(deps.require_permission("roles.view"))])
def list_roles(db: DbSession = Depends(deps.get_db)):
    roles = db.execute(select(Role).order_by(Role.id)).scalars().all()
    return [_out(db, r) for r in roles]


@router.get("/permissions", dependencies=[Depends(deps.require_permission("roles.view"))])
def list_permissions(db: DbSession = Depends(deps.get_db)):
    return [r.code for r in db.execute(select(Permission.code).order_by(Permission.code)).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_role(
    payload: schemas.CreateRoleRequest,
    db: DbSession = Depends(deps.get_db),
    actor: User = Depends(deps.require_permission("roles.administer")),
):
    if db.execute(select(Role).where(Role.name == payload.name)).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role exists.")
    role = Role(name=payload.name, description=payload.description)
    db.add(role)
    db.flush()
    for code in payload.permissions:
        perm = db.execute(select(Permission).where(Permission.code == code)).scalar_one_or_none()
        if perm is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown permission: {code}."
            )
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    db.flush()
    audit_service.log_event(
        db, actor_id=actor.id, action="role.create", entity="roles",
        entity_id=role.id, details={"name": payload.name, "permissions": payload.permissions},
    )
    db.commit()
    db.refresh(role)
    return _out(db, role)
