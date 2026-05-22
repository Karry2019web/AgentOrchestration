"""API middleware components."""

import time
import logging
import traceback
from typing import Callable, Optional, Dict, Any

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


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Clears request-local agent context after errors in async middleware.

    Sets the request-local agent context before dispatching to handlers
    and ensures it is cleared in a finally block after both success and
    error paths. This prevents context from leaking between requests
    and ensures that error responses do not expose sensitive state.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request.state._agent_context = {
            "method": request.method,
            "path": request.url.path,
            "timestamp": time.time(),
        }
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.error(
                "Unhandled exception in request %s %s: %s",
                request.method,
                request.url.path,
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
                headers={"X-Error-Sanitized": "true"},
            )
        finally:
            if hasattr(request.state, "_agent_context"):
                del request.state._agent_context


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")
        return response
