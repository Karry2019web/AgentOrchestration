"""API middleware components."""

import time
import logging
import re
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class NormalizePathMiddleware(BaseHTTPMiddleware):
    """Collapse duplicate slashes before public route matching.

    Ensures that paths like ``//api/v2//agents`` are normalized to
    ``/api/v2/agents`` before they reach the route table, auth
    middleware, or any downstream handler.  This prevents route
    misses, authentication bypasses on malformed paths, and cache
    fragmentation.
    """

    _DUPLICATE_SLASH_RE = re.compile(r"/{2,}")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        raw_path = request.url.path
        normalized = self._DUPLICATE_SLASH_RE.sub("/", raw_path)
        if normalized != raw_path:
            scope = dict(request.scope)
            scope["path"] = normalized
            scope["raw_path"] = normalized.encode("utf-8")
            request = Request(scope, receive=request.receive)
            logger.debug("Normalized path: %s -> %s", raw_path, normalized)
        return await call_next(request)


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
