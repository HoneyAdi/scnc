"""Baseline CSRF/origin protection for cookie-authenticated writes.

Policy (documented, fail-closed where it matters):
- Safe methods (GET/HEAD/OPTIONS) always pass through.
- State-changing methods require the request's Origin (preferred) or Referer to
  match the request's own host when either header is PRESENT. A mismatch is
  rejected with 403 before any handler runs.
- Absent Origin/Referer (non-browser clients, API tooling, tests) is allowed:
  blocking absent headers would break legitimate API use without adding real
  CSRF protection, since attackers cannot suppress headers the browser always
  sends on cross-site form/fetch POSTs. SameSite=Lax cookies + this check form
  the baseline; production must additionally serve over TLS (see startup gate).
"""
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host_of(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return (urlparse(value).hostname or "").lower() or None
    except Exception:
        return None


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        origin = _host_of(request.headers.get("origin")) or _host_of(
            request.headers.get("referer")
        )
        if origin is not None and origin != (request.url.hostname or "").lower():
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed."})
        return await call_next(request)
