"""API middleware components — auth validation with revoked key detection for long-polling."""

import time
import logging
from typing import Callable, Optional, Dict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.common.auth_service import api_key_service, Scope, get_required_scope, PUBLIC_PATHS
from src.common.errors import AuthenticationError

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        if path in PUBLIC_PATHS:
            return await call_next(request)

        if not path.startswith("/api/v2"):
            return await call_next(request)

        token = request.headers.get("Authorization", "")
        if not token.startswith("Bearer "):
            return Response(
                status_code=401,
                content='{"error":"Unauthorized","detail":"Missing or malformed Authorization header"}',
                media_type="application/json",
            )

        api_key = token[len("Bearer "):].strip()
        if not api_key:
            return Response(
                status_code=401,
                content='{"error":"Unauthorized","detail":"Empty API key in Authorization header"}',
                media_type="application/json",
            )

        required_scope = get_required_scope(path)

        # Revalidate on EVERY request including long-polling connections
        is_valid, reason, key_data = api_key_service.validate_key(api_key, required_scope)

        if not is_valid:
            status_code = 401 if "revoked" in reason.lower() or "expired" in reason.lower() else 403
            return Response(
                status_code=status_code,
                content=f'{{"error":"Unauthorized","detail":"{reason}"}}',
                media_type="application/json",
            )

        request.state.user = key_data.get("user", "unknown") if key_data else "unknown"
        request.state.workspace = key_data.get("workspace", "default") if key_data else "default"
        request.state.scopes = key_data.get("scopes", set()) if key_data else set()

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
        user = getattr(request.state, "user", "anonymous")
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s user={user}")
        return response
