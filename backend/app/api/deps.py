"""Request-scoped dependencies: DB session, current user, permission gates."""
from collections.abc import Generator

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.db.session import get_session
from app.models.auth import User
from app.services import auth_service


def get_db() -> Generator[DbSession, None, None]:
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def _token_from_request(request: Request) -> str | None:
    settings = get_settings()
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def get_current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    user = auth_service.validate_session(db, _token_from_request(request))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    return user


def require_permission(code: str):
    def guard(user: User = Depends(get_current_user), db: DbSession = Depends(get_db)) -> User:
        try:
            auth_service.require_permission(db, user, code)
        except auth_service.PermissionDenied:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")
        return user

    return guard


def current_token(request: Request) -> str | None:
    return _token_from_request(request)


def session_cookie_name() -> str:
    return get_settings().SESSION_COOKIE_NAME
