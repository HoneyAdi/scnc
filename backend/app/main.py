"""FastAPI application factory with logging, error handling, and health checks."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.csrf import OriginCheckMiddleware
from app.api.v1 import admin_audit, admin_roles, admin_users, accounts, auth, periods, setup
from app.core import logging_config
from app.core.config import get_settings
from app.core.logging_config import logger
from app.db.session import get_session
from app.services import bootstrap

logging_config.configure_logging()


def enforce_prod_security(settings) -> None:
    """Fail fast if production would run without TLS-grade session cookies.

    HTTP is NEVER safe for production credentials. Localhost development
    (ENV != prod) stays usable over plain HTTP.
    """
    if settings.ENV == "prod" and not settings.SESSION_SECURE_COOKIE:
        raise RuntimeError("Refusing to start: prod requires SESSION_SECURE_COOKIE=true (TLS).")


@asynccontextmanager
async def lifespan(app: FastAPI):
    enforce_prod_security(get_settings())
    db = get_session()
    try:
        token = bootstrap.ensure_setup_token(db)
        if token:
            path = bootstrap.write_setup_token_file(token)
            logger.warning("FIRST-TIME SETUP: initial Super Admin not created.")
            logger.warning("One-time setup credential written to restricted file: %s", path)
            logger.warning("It is valid 2h, single use. POST it with username+password to /api/v1/setup/admin.")
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SCN College Accounting API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "Invalid request."})

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "scn-api"}

    @app.get("/health/db")
    def health_db():
        db = get_session()
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ok", "database": "reachable"}
        except Exception:
            logger.exception("database health check failed")
            return JSONResponse(status_code=503, content={"status": "error", "database": "unreachable"})
        finally:
            db.close()

    prefix = "/api/v1"
    app.include_router(setup.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(admin_users.router, prefix=prefix)
    app.include_router(admin_roles.router, prefix=prefix)
    app.include_router(admin_audit.router, prefix=prefix)
    app.include_router(periods.router, prefix=prefix)
    app.include_router(accounts.router, prefix=prefix)
    return app


app = create_app()
