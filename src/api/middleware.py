"""API middleware components."""

import time
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .request_id import (
    REQUEST_ID_HEADER,
    BackgroundTaskWrapper,
    get_request_id,
    install_request_id_filters,
    request_id_context,
    sanitize_request_id,
)

logger = logging.getLogger(__name__)


class RequestIDLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces X-Request-ID on every request.

    * Reads or generates a X-Request-ID from the incoming request.
    * Sets the request ID in thread-local storage so logs carry it.
    * Wraps any FastAPI ``BackgroundTasks`` so they inherit the ID.
    * Returns the request ID in the response header.
    * Clears context in a ``finally`` block (no state leaking).
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        raw_id = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = sanitize_request_id(raw_id)
        install_request_id_filters()

        with request_id_context(request_id):
            # Wrap background tasks so they inherit this request ID
            bg_tasks = request.state.__dict__.get("background_tasks")
            if bg_tasks is not None:
                _wrap_background_tasks(bg_tasks, request_id)

            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response


def _wrap_background_tasks(bg_tasks, request_id: str) -> None:
    """Replace every task in *bg_tasks* with a :class:`BackgroundTaskWrapper`."""
    for i, task in enumerate(bg_tasks.tasks):
        if not isinstance(task, BackgroundTaskWrapper):
            wrapped = BackgroundTaskWrapper(
                request_id, task.func, *task.args, **task.kwargs
            )
            bg_tasks.tasks[i] = wrapped


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
