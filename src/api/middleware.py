"""API middleware components."""

import time
import uuid
import logging
from typing import Callable, Optional, Dict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Request-local context store (contextvars would be preferred, but
# Starlette middleware runs in the same event loop so we use a dict
# keyed by correlation ID for cross-middleware visibility)
_request_context: Dict[str, Dict] = {}


def get_correlation_id() -> Optional[str]:
    """Return the current request's correlation ID, if set."""
    return None


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Attach and propagate correlation IDs per request.

    Every inbound request receives a unique correlation ID.  If the
    caller sends an ``X-Correlation-ID`` header its value is used as
    the root; otherwise a new UUID is generated.  The ID is stored on
    ``request.state.correlation_id`` so downstream handlers and
    middleware can reference it without needing request-local globals.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract or generate correlation ID
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Attach to request state
        request.state.correlation_id = correlation_id
        request.state.tenant_id = request.headers.get("X-Tenant-ID", "default")

        # Prepare context dict for this request
        ctx = {
            "correlation_id": correlation_id,
            "tenant_id": request.state.tenant_id,
            "path": request.url.path,
            "method": request.method,
        }
        _request_context[correlation_id] = ctx

        response = Response()
        try:
            response = await call_next(request)
            return response
        finally:
            # Always clear request-local state, even on exception
            _request_context.pop(correlation_id, None)
            # Ensure correlation ID is set on the response
            if correlation_id and correlation_id not in response.headers.get("X-Correlation-ID", ""):
                response.headers["X-Correlation-ID"] = correlation_id


class TenantScopeMiddleware(BaseHTTPMiddleware):
    """Enforce tenant scoping on every request.

    Every authenticated request is scoped to a workspace/tenant.
    This middleware verifies that the tenant derived from the request
    matches the authenticated principal's tenant, preventing
    correlation IDs and context from crossing tenant boundaries.

    For unauthenticated requests (no Bearer token) the middleware
    still tags the request with a default tenant scope so that
    downstream code never operates without a tenant context.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Determine tenant from header or auth context
        tenant_id = request.headers.get("X-Tenant-ID", "default")

        # If auth token is present, verify tenant match
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            # Simple tenant derivation from token prefix
            token_tenant = _derive_tenant_from_token(token)
            if token_tenant and token_tenant != tenant_id:
                logger.warning(
                    "Tenant mismatch: header tenant=%s token tenant=%s path=%s",
                    tenant_id, token_tenant, request.url.path,
                )
                return Response(
                    status_code=403,
                    content="Tenant mismatch: request scoped to wrong workspace",
                )

        request.state.tenant_id = tenant_id
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id and correlation_id in _request_context:
            _request_context[correlation_id]["tenant_id"] = tenant_id

        return await call_next(request)


def _derive_tenant_from_token(token: str) -> Optional[str]:
    """Derive a tenant identifier from an opaque bearer token.

    This is a simplistic implementation. In a real system the token
    would be a JWT whose payload contains ``tenant_id`` or
    ``workspace_id``.
    """
    if token.startswith("tenant-") and token.endswith("-token"):
        return token[len("tenant-"):-len("-token")]
    if len(token) >= 8:
        return f"tenant-{token[:8]}"
    return None


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
        correlation_id = getattr(request.state, "correlation_id", None)
        tenant_id = getattr(request.state, "tenant_id", "default")
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            "[correlation=%s] [tenant=%s] %s %s %s %.3fs",
            correlation_id or "-",
            tenant_id,
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response
