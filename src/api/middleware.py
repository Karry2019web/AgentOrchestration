"""API middleware components with JWT audience enforcement."""

import time
import logging
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .auth import token_service, TokenValidationError, AGENT_WORKER_AUDIENCE

logger = logging.getLogger(__name__)


# Paths that do not require authentication
PUBLIC_PATHS = {
    "/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/api/v2/auth/token",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates JWT tokens and enforces audience for every protected API call.

    - Browser clients must present tokens with audience "browser-ui".
    - Service-to-service (agent worker) callers must present tokens with
      audience "agent-worker-api".
    - Tokens must be signed, not expired, and not revoked.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip authentication for public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Only protect /api/v2 routes
        if not request.url.path.startswith("/api/v2"):
            return await call_next(request)

        # Extract token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return Response(
                status_code=401,
                content='{"error":"Missing or malformed Authorization header"}',
                media_type="application/json",
            )

        token = auth_header[7:]

        # Detect caller type from header or path pattern
        # Agent-worker calls include X-Caller-Type: service
        caller_type = request.headers.get("X-Caller-Type", "browser")

        try:
            if caller_type == "service":
                payload = token_service.validate_service_token(token)
            else:
                payload = token_service.validate_browser_token(token)
        except TokenValidationError as e:
            logger.warning(f"Auth failed for {request.url.path}: {e}")
            return Response(
                status_code=401,
                content=f'{{"error":"{e}"}}',
                media_type="application/json",
            )

        # Attach validated claims to request scope for downstream handlers
        request.state.auth_payload = payload
        request.state.auth_caller_type = caller_type

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
        auth_info = ""
        if hasattr(request.state, 'auth_caller_type'):
            auth_info = f" [{request.state.auth_caller_type}]"
        logger.info(f"{request.method} {request.url.path}{auth_info} {response.status_code} {duration:.3f}s")
        return response
