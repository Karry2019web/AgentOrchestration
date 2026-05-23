"""API middleware components."""

import time
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

SSE_CONTENT_TYPE = "text/event-stream"


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


class CompressionLimitMiddleware(BaseHTTPMiddleware):
    """Limit response compression on SSE (text/event-stream) endpoints.

    SSE streams can produce unbounded output; applying compression on them
    consumes CPU and memory without meaningful benefit. This middleware
    strips the Accept-Encoding header from SSE requests so downstream
    compression middleware (e.g. Starlette's GZipMiddleware) skips them,
    and sets the response Content-Encoding to identity on SSE responses.

    Normal requests pass through unchanged.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        accept = request.headers.get("accept", "")
        is_sse_request = SSE_CONTENT_TYPE in accept

        if is_sse_request:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-cache"
            response.headers["X-Accel-Buffering"] = "no"
            response.headers["Content-Encoding"] = "identity"
            logger.debug(f"SSE compression bypassed for {request.url.path}")
            return response

        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if SSE_CONTENT_TYPE in content_type:
            response.headers["Content-Encoding"] = "identity"
            response.headers["X-Accel-Buffering"] = "no"

        return response
