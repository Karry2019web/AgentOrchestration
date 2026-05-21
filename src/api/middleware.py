"""API middleware components."""

import os
import time
import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

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
    """Limit incoming request body size to protect against oversized payloads.

    Returns 411 (Length Required), 400 (Bad Request), or 413 (Payload Too Large)
    when the Content-Length header is missing, invalid, or exceeds the limit.
    """

    def __init__(self, app, max_bytes: int = 10 * 1024 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")

        if content_length is None:
            if request.method in ("POST", "PUT", "PATCH"):
                return Response(status_code=411, content="Length Required")
            return await call_next(request)

        try:
            size = int(content_length)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})

        if size < 0:
            return Response(status_code=411, content="Length Required")

        if size > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body exceeds maximum size of {self.max_bytes} bytes"}
            )

        return await call_next(request)
