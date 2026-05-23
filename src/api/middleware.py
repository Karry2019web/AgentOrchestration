"""API middleware components with separated machine/user token permissions."""

import time
import logging
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.common.auth import (
    AuthValidator,
    AuthError,
    Scope,
    TokenType,
    TokenInfo,
)

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforces authentication and authorisation on API v2 routes.

    Validates bearer tokens, distinguishes machine tokens from user tokens,
    and applies appropriate scope-based access control.  Rejects stale,
    revoked, expired, anonymous, and insufficiently-scoped principals.
    """

    def __init__(self, app, validator=None):
        super().__init__(app)
        self._validator = validator or AuthValidator()

    async def dispatch(self, request, call_next):
        # 1. Skip the token endpoint itself so clients can obtain tokens.
        path = request.url.path
        if path == "/api/v2/auth/token":
            return await call_next(request)

        # 2. Only protect /api/v2 endpoints.
        if not path.startswith("/api/v2"):
            return await call_next(request)

        # 3. Extract the raw token from the Authorization header.
        raw_token = request.headers.get("Authorization", "")

        if not raw_token:
            return Response(
                status_code=401,
                content='{"error":"Missing Authorization header"}',
                media_type="application/json",
            )

        # 4. Classify the token type before full validation.
        token_type = self._validator.classify_token(raw_token)
        if token_type == TokenType.ANONYMOUS:
            return Response(
                status_code=401,
                content='{"error":"Anonymous access denied - provide a valid Bearer token"}',
                media_type="application/json",
            )

        # 5. Derive required scopes from the request.
        required_scopes = Scope.from_route(request.method, path)

        # 6. Full validation.
        try:
            token_info = self._validator.validate(
                raw_token, required_scopes=required_scopes or None,
            )
        except AuthError as exc:
            return Response(
                status_code=exc.status_code,
                content='{"error":"' + exc.message + '"}',
                media_type="application/json",
            )

        # 7. Attach validated token info to request state so downstream
        #    handlers can inspect it.
        request.state.token_info = token_info
        request.state.token_type = token_type

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests=100, window=60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(self, request, call_next):
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
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        token_type = getattr(request.state, "token_type", "unknown")
        logger.info(
            f"{request.method} {request.url.path} "
            f"{response.status_code} {duration:.3f}s "
            f"[{token_type.value if hasattr(token_type, 'value') else token_type}]"
        )
        return response
