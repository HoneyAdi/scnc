"""First-time setup endpoints (disabled once initialized)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.api import deps, schemas
from app.services import bootstrap

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status")
def setup_status(db: DbSession = Depends(deps.get_db)):
    return {"initialized": bootstrap.is_initialized(db)}


@router.post("/admin", status_code=status.HTTP_201_CREATED)
def setup_admin(payload: schemas.SetupRequest, db: DbSession = Depends(deps.get_db)):
    try:
        user = bootstrap.consume_setup_token(
            db, token=payload.token, username=payload.username, password=payload.password
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"id": user.id, "username": user.username}
