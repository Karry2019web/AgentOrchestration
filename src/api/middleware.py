"""API middleware components."""

import contextvars
import hashlib
import time
import logging
import uuid
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Per-request context vars for tenant-isolated correlation
_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
_tenant_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default="")
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def get_correlation_id() -> str:
    return _correlation_id_var.get()


def get_tenant_id() -> str:
    return _tenant_id_var.get()


def get_request_id() -> str:
    return _request_id_var.get()


class TenantCorrelationMiddleware(BaseHTTPMiddleware):
    """Enforces tenant-bound correlation IDs across requests.

    - Assigns per-request correlation and request IDs.
    - Scopes correlation IDs to the authenticated tenant (from X-Tenant-Id header).
    - Rejects requests where the correlation ID header implies a different tenant.
    - Clears all context vars in finally blocks (success, rejection, exception).
    - Adds X-Correlation-Id and X-Request-Id response headers.
    """

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
        tenant_id = request.headers.get("X-Tenant-Id", "default")
        role = request.headers.get("X-Role", "viewer")

        # Scoped correlation IDs: if a correlation ID already contains a tenant
        # prefix, it must match the current request's tenant
        if ":" in correlation_id:
            embedded_tenant = correlation_id.split(":", 1)[0]
            if embedded_tenant != tenant_id:
                logger.warning(
                    f"Rejected request {request_id}: correlation ID tenant "
                    f"'{embedded_tenant}' does not match header tenant '{tenant_id}'"
                )
                return Response(
                    status_code=403,
                    content="Correlation ID tenant mismatch",
                    headers={
                        "X-Request-Id": request_id,
                        "X-Correlation-Id": correlation_id,
                    },
                )

        # Prefixed correlation ID with tenant scope
        scoped_correlation = f"{tenant_id}:{correlation_id.split(':', 1)[-1]}"

        # Set context vars for downstream use
        token_c = _correlation_id_var.set(scoped_correlation)
        token_t = _tenant_id_var.set(tenant_id)
        token_r = _request_id_var.set(request_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id

            # Only send scoped correlation header if not already set downstream
            if "X-Correlation-Id" not in response.headers:
                response.headers["X-Correlation-Id"] = scoped_correlation

            # Sanitized log: hash the tenant for log safety
            tenant_hash = hashlib.sha256(tenant_id.encode()).hexdigest()[:8]
            logger.debug(
                f"{request.method} {request.url.path} "
                f"corr={scoped_correlation[:16]} "
                f"tenant={tenant_hash} "
                f"status={response.status_code}"
            )
            return response
        except Exception:
            logger.exception(
                f"Unhandled exception for request {request_id} "
                f"(correlation={scoped_correlation[:16]})"
            )
            return Response(
                status_code=500,
                content="Internal Server Error",
                headers={"X-Request-Id": request_id},
            )
        finally:
            _correlation_id_var.reset(token_c)
            _tenant_id_var.reset(token_t)
            _request_id_var.reset(token_r)


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
