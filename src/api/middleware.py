"""API middleware components."""

import time
import uuid
import logging
import contextvars
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Context vars for per-request state isolation
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
tenant_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default="")
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def get_correlation_id() -> str:
    """Get the current request's correlation ID."""
    return correlation_id_var.get()


def get_tenant_id() -> str:
    """Get the current request's tenant ID."""
    return tenant_id_var.get()


def get_request_id() -> str:
    """Get the current request's unique ID."""
    return request_id_var.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware that establishes per-request context with tenant-scoped correlation IDs.

    This middleware ensures correlation IDs and tenant context are properly scoped
    to each individual request and never leak across requests. Context is set up
    before the request handler runs and is always cleaned up in a finally block
    to prevent cross-tenant contamination.
    """

    CORRELATION_HEADER = "X-Correlation-ID"
    TENANT_HEADER = "X-Tenant-ID"
    REQUEST_ID_HEADER = "X-Request-ID"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or extract correlation ID from incoming request
        correlation_id = request.headers.get(
            self.CORRELATION_HEADER,
            str(uuid.uuid4()),
        )
        # Extract tenant from header or default to "anonymous"
        tenant_id = request.headers.get(
            self.TENANT_HEADER,
            "anonymous",
        )
        request_id = str(uuid.uuid4())

        # Set context vars for this request
        correlation_id_token = correlation_id_var.set(correlation_id)
        tenant_id_token = tenant_id_var.set(tenant_id)
        request_id_token = request_id_var.set(request_id)

        try:
            response = await call_next(request)
            # Attach correlation and request IDs to response headers
            response.headers[self.CORRELATION_HEADER] = correlation_id
            response.headers[self.REQUEST_ID_HEADER] = request_id
            if tenant_id != "anonymous":
                response.headers[self.TENANT_HEADER] = tenant_id
            return response
        except Exception as exc:
            # On error, still return a proper response with tracing headers
            logger.error(
                "Request failed",
                extra={
                    "correlation_id": correlation_id,
                    "tenant_id": tenant_id,
                    "request_id": request_id,
                    "error": str(exc),
                },
            )
            import traceback
            error_response = Response(
                status_code=500,
                content=f"Internal server error (request_id={request_id})",
            )
            error_response.headers[self.CORRELATION_HEADER] = correlation_id
            error_response.headers[self.REQUEST_ID_HEADER] = request_id
            if tenant_id != "anonymous":
                error_response.headers[self.TENANT_HEADER] = tenant_id
            return error_response
        finally:
            # Critical: reset context vars to prevent cross-request leakage
            correlation_id_var.reset(correlation_id_token)
            tenant_id_var.reset(tenant_id_token)
            request_id_var.reset(request_id_token)


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
        correlation_id = correlation_id_var.get()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s",
            extra={
                "correlation_id": correlation_id,
                "duration": duration,
            },
        )
        return response
