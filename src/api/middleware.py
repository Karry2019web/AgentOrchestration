"""API middleware components."""

import time
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .auth import validate_token, User

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Enhanced authentication middleware with role-based access control.

    Validates Bearer tokens on /api/v2 routes, sets request.state.user
    for downstream route handlers, and returns 401 for invalid tokens.
    The /api/v2/auth/token endpoint is excluded from auth checks.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            token = request.headers.get("Authorization", "")

            if not token.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized")

            token_value = token.removeprefix("Bearer ").strip()
            user = validate_token(token_value)

            if user is None:
                return Response(
                    status_code=401,
                    content='{"detail": "Invalid or expired token"}',
                    media_type="application/json",
                )

            # Attach validated user to request state for downstream use
            request.state.user = user
        else:
            request.state.user = None

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
        user_info = ""
        if hasattr(request.state, "user") and request.state.user:
            user_info = f" user={request.state.user.username}"
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s{user_info}")
        return response
