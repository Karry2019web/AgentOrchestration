"""API middleware components."""

import time
import asyncio
import logging
from contextvars import ContextVar
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Request-local context for cancellation propagation
_request_cancelled: ContextVar[bool] = ContextVar("request_cancelled", default=False)
_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class CancellationPropagationMiddleware(BaseHTTPMiddleware):
    """Propagate cancellation signals to downstream agent calls.

    Ensures that when a request is cancelled (e.g., client disconnect, timeout),
    the cancellation is propagated to all downstream work and request-local
    state is cleaned up atomically.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        req_id = request.headers.get("X-Request-ID", "")
        token_cancelled = _request_cancelled.set(False)
        token_req_id = _request_id.set(req_id)
        try:
            response = await call_next(request)
            return response
        except asyncio.CancelledError:
            _request_cancelled.set(True)
            logger.warning("Request cancelled, propagating to downstream: req_id=%s", req_id)
            raise
        except Exception:
            logger.exception("Unhandled exception in middleware: req_id=%s", req_id)
            raise
        finally:
            _request_cancelled.reset(token_cancelled)
            _request_id.reset(token_req_id)
            logger.debug("Cleared request-local context for req_id=%s", req_id)


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

# {now} update
