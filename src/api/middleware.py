"""API middleware components."""

import time
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

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


class SSEMiddleware(BaseHTTPMiddleware):
    """Limits response compression on Server-Sent Events (SSE) streams.

    SSE endpoints must deliver events as uncompressed text/event-stream.
    Standard HTTP compression (gzip/deflate) buffers the entire stream
    before flushing, which breaks real-time delivery and increases
    memory usage. This middleware detects SSE responses and ensures
    compression is bypassed while still applying before-expensive-work
    input validation.
    """

    SSE_PATH_PREFIXES = ("/api/v2/events", "/api/v2/stream", "/events")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        is_sse = any(request.url.path.startswith(prefix)
                     for prefix in self.SSE_PATH_PREFIXES)

        if not is_sse:
            return await call_next(request)

        # Validate Accept header — reject non-SSE clients early
        accept = request.headers.get("Accept", "")
        if "text/event-stream" not in accept and accept != "*/*":
            return Response(
                status_code=406,
                content="SSE endpoint requires Accept: text/event-stream",
            )

        response = await call_next(request)

        # If the downstream handler returned a StreamingResponse, ensure
        # its media type is correct and disable implicit compression.
        if isinstance(response, StreamingResponse):
            response.headers["Content-Type"] = "text/event-stream"
            response.headers["Cache-Control"] = "no-cache"
            response.headers["X-Accel-Buffering"] = "no"
            response.headers["Connection"] = "keep-alive"

        return response
