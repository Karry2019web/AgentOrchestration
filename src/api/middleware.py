"""API middleware components — JWT auth, rate limiting, logging."""

import time
import logging
import os
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.common.auth import validate_service_token

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates JWT tokens on protected API routes.

    Requires a valid Bearer JWT with the correct audience for all
    /api/v2 endpoints except /api/v2/auth/token.

    The expected audience is configurable via AO_JWT_AUDIENCE env var
    (default: "agent-orchestrator").
    """

    def __init__(self, app):
        super().__init__(app)
        self._audience = os.getenv("AO_JWT_AUDIENCE", "agent-orchestrator")
        self._allowed_issuers_str = os.getenv("AO_JWT_ALLOWED_ISSUERS", "")
        self._allowed_issuers: Optional[list] = (
            [s.strip() for s in self._allowed_issuers_str.split(",") if s.strip()]
            if self._allowed_issuers_str
            else None
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return Response(
                    status_code=401,
                    content='{"error":"Missing or malformed Authorization header"}',
                    media_type="application/json",
                )

            token = auth_header[len("Bearer "):]
            is_valid, error, payload = validate_service_token(
                token,
                expected_audience=self._audience,
                allowed_issuers=self._allowed_issuers,
            )

            if not is_valid:
                logger.warning(f"Auth rejected: {error}")
                return Response(
                    status_code=401,
                    content=f'{{"error":"{error}"}}',
                    media_type="application/json",
                )

            # Attach validated claims to request state for downstream handlers
            request.state.token_payload = payload

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
