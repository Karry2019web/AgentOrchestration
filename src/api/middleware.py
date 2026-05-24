"""API middleware components."""

import os
import time
import logging
from typing import Callable, List, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Default CORS allowlist for credentialed requests.
# When allow_credentials=True, the Access-Control-Allow-Origin must be
# a specific origin, not "*", per the CORS specification (Fetch §4.2).
_DEFAULT_CORS_ALLOWLIST = os.getenv(
    "CORS_ALLOWLIST",
    "https://app.agentorchestrator.io,https://dashboard.agentorchestrator.io",
).split(",")


class CorsAllowlistMiddleware(BaseHTTPMiddleware):
    """Enforce CORS allowlist on credentialed requests.

    Starlette's CORSMiddleware sends ``Access-Control-Allow-Origin: *`` when
    ``allow_origins=["*"]``, but this violates the CORS specification for
    credentialed requests (Fetch §4.2): ``Access-Control-Allow-Origin`` must
    be the literal origin value, not a wildcard.

    This middleware sits AFTER CORSMiddleware in the chain and rewrites the
    header so that credentialed requests get an explicit origin echoed back
    **only if** the request's ``Origin`` is in the configured allowlist.
    Origins outside the allowlist receive a 403 Forbidden response.

    Configure via environment variable ``CORS_ALLOWLIST`` (comma-separated).
    """

    def __init__(self, app, allowlist: Optional[List[str]] = None):
        super().__init__(app)
        self.allowlist = [o.rstrip("/") for o in (allowlist or _DEFAULT_CORS_ALLOWLIST)]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only enforce for credentialed requests that include an Origin header
        origin = request.headers.get("Origin")
        if not origin or request.method in ("GET", "HEAD", "OPTIONS"):
            # Non-credentialed or simple requests are handled by CORSMiddleware
            return await call_next(request)

        origin_stripped = origin.rstrip("/")

        # Check whether the origin is in the allowlist
        if origin_stripped in self.allowlist:
            response = await call_next(request)
            # Override Access-Control-Allow-Origin to echo the specific origin
            # (CORSMiddleware may have set it to "*" which browsers reject)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = _merge_vary(
                response.headers.get("Vary", ""), "Origin"
            )
            return response

        # Origin not in allowlist — reject with 403
        logger.warning(
            "CORS blocked origin=%s method=%s path=%s",
            origin,
            request.method,
            request.url.path,
        )
        return Response(
            status_code=403,
            content=b"Origin not allowed: " + origin.encode(),
            media_type="text/plain",
        )


def _merge_vary(current: str, header: str) -> str:
    """Add *header* to the Vary response header unless already present."""
    parts = [p.strip() for p in current.split(",") if p.strip()]
    if header not in parts:
        parts.append(header)
    return ", ".join(parts)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            token = request.headers.get("Authorization", "")
            if not token.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [t for t in self._requests[client_ip] if now - t < self.window]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(status_code=429, content="Too many requests")

        self._requests[client_ip].append(now)
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")
        return response
