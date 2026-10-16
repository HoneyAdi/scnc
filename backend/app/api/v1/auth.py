"""Login/logout/session endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as DbSession

from app.api import deps, schemas
from app.core.config import get_settings
from app.models.auth import User
from app.services import auth_service

router = APIRouter(tags=["auth"])


def _user_out(db: DbSession, user: User) -> schemas.UserOut:
    return schemas.UserOut(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        permissions=sorted(auth_service.user_permissions(db, user.id)),
    )


@router.post("/auth/login")
def login(
    payload: schemas.LoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(deps.get_db),
):
    settings = get_settings()
    ip = request.client.host if request.client else None
    try:
        user, token = auth_service.authenticate(db, payload.username, payload.password, ip)
    except auth_service.LockedError as exc:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(exc))
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.SESSION_SECURE_COOKIE,
        max_age=settings.SESSION_EXPIRE_MINUTES * 60,
        path="/",
    )
    return {"user": _user_out(db, user), "token": token}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(deps.get_db)):
    token = deps.current_token(request)
    settings = get_settings()
    user = auth_service.validate_session(db, token) if token else None
    if token:
        auth_service.logout(db, token, actor_id=user.id if user else None)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(deps.get_current_user), db: DbSession = Depends(deps.get_db)):
    return _user_out(db, user)
