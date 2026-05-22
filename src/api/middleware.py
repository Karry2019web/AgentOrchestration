"""API middleware components with least-privilege operator token enforcement."""

import time
import logging
from typing import Callable, Optional, Set
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.common.auth import (
    OperatorTokenService,
    TokenValidationResult,
    TokenScope,
    get_operator_token_service,
)

logger = logging.getLogger(__name__)

_RUN_CANCELLATION_SCOPES: Set[str] = {TokenScope.RUN_CANCEL.value, TokenScope.ADMIN.value}
_AGENT_DELETE_SCOPES: Set[str] = {TokenScope.AGENT_DELETE.value, TokenScope.ADMIN.value}


def _extract_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header[len("Bearer "):].strip()


def _extract_workspace(request: Request) -> str:
    return request.headers.get("X-Workspace-Id", "default")


class AuthMiddleware(BaseHTTPMiddleware):
    """Enhanced auth middleware that validates operator tokens and enforces scopes."""

    def __init__(self, app, auth_service: Optional[OperatorTokenService] = None):
        super().__init__(app)
        self.auth_service = auth_service or get_operator_token_service()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method

        if path in ("/health", "/api/v2/auth/token"):
            return await call_next(request)

        token = _extract_token(request)
        if not token:
            return Response(
                status_code=401,
                content='{"error":"Unauthorized","reason":"missing_token"}',
                media_type="application/json",
            )

        required_scopes = self._get_required_scopes(method, path)
        validation = self.auth_service.validate_token(token, required_scopes=required_scopes)

        if validation == TokenValidationResult.MALFORMED:
            return Response(status_code=401, content='{"error":"Unauthorized","reason":"malformed_token"}', media_type="application/json")
        if validation == TokenValidationResult.EXPIRED:
            return Response(status_code=401, content='{"error":"Unauthorized","reason":"token_expired"}', media_type="application/json")
        if validation == TokenValidationResult.REVOKED:
            return Response(status_code=403, content='{"error":"Forbidden","reason":"token_revoked"}', media_type="application/json")
        if validation == TokenValidationResult.INSUFFICIENT_SCOPE:
            return Response(status_code=403, content='{"error":"Forbidden","reason":"insufficient_scope"}', media_type="application/json")

        if method == "POST" and path.endswith("/stop"):
            workspace = _extract_workspace(request)
            ws_validation = self.auth_service.validate_run_cancellation(token, workspace)
            if ws_validation == TokenValidationResult.WRONG_WORKSPACE:
                return Response(status_code=403, content='{"error":"Forbidden","reason":"wrong_workspace"}', media_type="application/json")

        return await call_next(request)

    @staticmethod
    def _get_required_scopes(method: str, path: str) -> Optional[Set[str]]:
        if method == "POST" and path.endswith("/stop"):
            return _RUN_CANCELLATION_SCOPES
        if method == "DELETE" and "/agents/" in path:
            return _AGENT_DELETE_SCOPES
        if method == "POST" and "/agents" in path:
            return {TokenScope.AGENT_WRITE.value, TokenScope.ADMIN.value}
        if method == "GET" and "/agents" in path:
            return {TokenScope.AGENT_READ.value, TokenScope.ADMIN.value}
        return None


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
