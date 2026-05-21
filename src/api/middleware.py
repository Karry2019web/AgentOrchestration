"""API middleware components."""

import time
import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


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


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforce maximum request body size on artifact upload endpoints.

    Validates Content-Length header before the request body is read,
    preventing oversized artifacts from consuming server resources or
    bypassing artifact size limits.
    """

    DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB

    def __init__(self, app, max_bytes: Optional[int] = None):
        super().__init__(app)
        self.max_bytes = max_bytes or self.DEFAULT_MAX_BYTES

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2/artifacts/upload"):
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    size = int(content_length)
                    if size <= 0:
                        return Response(
                            status_code=411,
                            content="Content-Length must be a positive integer",
                        )
                    if size > self.max_bytes:
                        return Response(
                            status_code=413,
                            content=f"Request body exceeds maximum allowed size of {self.max_bytes} bytes",
                        )
                except (ValueError, TypeError):
                    return Response(
                        status_code=400,
                        content="Invalid Content-Length header",
                    )
            else:
                # No Content-Length provided — reject early to avoid unbounded reads
                return Response(
                    status_code=411,
                    content="Content-Length header is required",
                )
        return await call_next(request)

