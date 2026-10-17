"""Origin validation for cookie-authenticated writes.

Policy:
- Safe methods (GET/HEAD/OPTIONS) always pass through.
- For state-changing methods, compare the FULL origin triple
  (scheme, hostname, effective port) — a different scheme or port is NOT
  same-origin even when the hostname matches.
- The request is allowed when its Origin (preferred) or Referer triple equals
  EITHER the request's own triple (same-origin) OR one of the configured
  trusted origins (`CORS_ORIGINS`, e.g. a LAN frontend on another host).
- Absent Origin AND Referer means a non-browser API client: allowed, because
  blocking absent headers would break legitimate API use without adding real
  CSRF protection (attackers cannot suppress headers the browser always sends
  on cross-site form/fetch POSTs). Browser cookie sessions additionally carry
  SameSite=Lax; production must serve over TLS (see startup gate).
- A PRESENT but malformed/unparseable Origin or Referer is rejected (403):
  fail closed rather than guessing.
"""
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def parse_origin(value: str | None) -> tuple[str, str, int] | None:
    """Parse an origin into (scheme, hostname, effective port) or None if unusable."""
    if not value:
        return None
    try:
        parts = urlparse(value)
    except Exception:
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    port = parts.port or _DEFAULT_PORTS[scheme]
    return (scheme, host, port)


def trusted_origins() -> set[tuple[str, str, int]]:
    result = set()
    for raw in get_settings().CORS_ORIGINS:
        parsed = parse_origin(raw)
        if parsed is not None:
            result.add(parsed)
    return result


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        presented = parse_origin(request.headers.get("origin"))
        if presented is None:
            presented = parse_origin(request.headers.get("referer"))
        if presented is None:
            if request.headers.get("origin") is not None or request.headers.get("referer") is not None:
                # Header present but malformed: fail closed.
                return JSONResponse(status_code=403, content={"detail": "Origin not allowed."})
            return await call_next(request)  # non-browser API client
        scheme = request.url.scheme.lower()
        host = (request.url.hostname or "").lower()
        port = request.url.port or _DEFAULT_PORTS.get(scheme, 0)
        if presented == (scheme, host, port):
            return await call_next(request)  # same-origin
        if presented in trusted_origins():
            return await call_next(request)  # explicitly trusted deployment origin
        return JSONResponse(status_code=403, content={"detail": "Origin not allowed."})
