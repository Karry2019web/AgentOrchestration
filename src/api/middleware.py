"""API middleware components."""

import time
import logging
from typing import Callable, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


def validate_token(token_value: str) -> Tuple[bool, str, str]:
    """Validate a bearer token and return (is_valid, token_type, principal).

    Token format: Bearer <type_prefix>_<id>.<signature>
    - Machine tokens: mch_<id>.<sig>   -- CI/CD, automated workflows
    - User tokens:    usr_<id>.<sig>   -- browser sessions, CLI logins

    Returns:
        (True, token_type, principal) on success
        (False, reason, "") on failure
    """
    if not token_value or not token_value.startswith("Bearer "):
        return (False, "missing_auth_header", "")

    raw = token_value[len("Bearer "):].strip()
    if not raw:
        return (False, "empty_token", "")

    if raw.startswith("mch_"):
        parts = raw.split(".", 1)
        if len(parts) != 2 or len(parts[1]) < 16:
            return (False, "malformed_machine_token", "")
        return (True, "machine", raw)

    elif raw.startswith("usr_"):
        parts = raw.split(".", 1)
        if len(parts) != 2 or len(parts[1]) < 16:
            return (False, "malformed_user_token", "")
        return (True, "user", raw)

    else:
        return (False, "unknown_token_type", "")


def authorize(token_type: str, method: str, path: str) -> Tuple[bool, str]:
    """Check if token_type has permission for method:path.

    Rules:
    - Machine tokens: full CRUD on agents
    - User tokens: read-only on agents, can manage own session
    """
    if (method, "/api/v2/auth/token") in {("POST", "/api/v2/auth/token")}:
        if token_type == "user":
            return (True, "")
        return (False, "machine_tokens_cannot_manage_user_auth")

    if path == "/health":
        return (True, "")

    if method in ("POST", "DELETE", "PUT", "PATCH") and path.startswith("/api/v2/agents"):
        if token_type == "machine":
            return (True, "")
        return (False, "user_tokens_are_read_only_for_agents")

    if method == "GET" and path.startswith("/api/v2/agents"):
        return (True, "")

    return (True, "")


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforces token-type-aware authentication and authorization.

    Machine tokens (mch_*) -> full CRUD automation access
    User tokens (usr_*)    -> read-only agent access, session management
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method

        if not path.startswith("/api/v2"):
            return await call_next(request)

        if path == "/api/v2/auth/token":
            return await call_next(request)

        token_header = request.headers.get("Authorization", "")
        is_valid, token_type_or_reason, principal = validate_token(token_header)

        if not is_valid:
            logger.warning("Auth failed: %s for %s %s", token_type_or_reason, method, path)
            return Response(
                status_code=401,
                content="Unauthorized: %s" % token_type_or_reason,
            )

        allowed, reason = authorize(token_type_or_reason, method, path)
        if not allowed:
            logger.warning(
                "Authorization denied: %s token cannot %s %s (%s)",
                token_type_or_reason, method, path, reason,
            )
            return Response(
                status_code=403,
                content="Forbidden: insufficient permissions for this token type",
            )

        request.state.token_type = token_type_or_reason
        request.state.principal = principal

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
        logger.info("%s %s %s %.3fs", request.method, request.url.path, response.status_code, duration)
        return response
