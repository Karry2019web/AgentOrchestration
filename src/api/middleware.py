"""API middleware components."""

import asyncio
import time
import logging
from typing import Callable
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
        try:
            response = await call_next(request)
            return response
        except asyncio.CancelledError:
            duration = time.time() - start
            logger.warning(f"Cancelled {request.method} {request.url.path} after {duration:.3f}s")
            raise
        finally:
            duration = time.time() - start
            logger.info(f"{request.method} {request.url.path} {duration:.3f}s")


class CancellationPropagationMiddleware(BaseHTTPMiddleware):
    """Propagate cancellation to downstream agent calls.

    When a request is cancelled (client disconnect, timeout, or server shutdown),
    BaseHTTPMiddleware may swallow asyncio.CancelledError. This middleware catches
    the cancellation, cancels any tracked downstream agent tasks, waits for them
    to settle, and re-raises the CancelledError so the entire call chain halts
    in a consistent terminal state.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        downstream_tasks = set()
        request.state._downstream_tasks = downstream_tasks

        try:
            return await call_next(request)
        except asyncio.CancelledError:
            # Cancel all tracked downstream agent calls
            for task in downstream_tasks:
                if not task.done():
                    task.cancel()
            if downstream_tasks:
                await asyncio.gather(*downstream_tasks, return_exceptions=True)
            raise
        finally:
            request.state._downstream_tasks = None
