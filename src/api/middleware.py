"""API middleware components."""

import contextvars
import time
import logging
import re
from uuid import uuid4
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

current_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_request_id", default=None
)
_validation_error_reason: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_validation_error_reason", default=None
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            token = request.headers.get("Authorization", "")
            if not token.startswith("Bearer "):
                return Response(status_code=401, content='{"error":"Unauthorized"}', media_type="application/json")
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests: dict = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [t for t in self._requests[client_ip] if now - t < self.window]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(status_code=429, content='{"error":"Too many requests"}', media_type="application/json")

        self._requests[client_ip].append(now)
        return await call_next(request)


class ValidationMiddleware(BaseHTTPMiddleware):
    _AGENT_PATH_PATTERN = re.compile(r"^/api/v2/agents(?:/[a-zA-Z0-9_-]+(?:/(?:start|stop))?)?$")
    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        token = current_request_id.set(request_id)
        error_token = _validation_error_reason.set(None)

        try:
            path = request.url.path
            if path.startswith("/api/v2"):
                if path not in ("/api/v2/auth/token", "/health", "/api/docs", "/api/redoc", "/openapi.json"):
                    if not self._AGENT_PATH_PATTERN.match(path):
                        _validation_error_reason.set("invalid_path")
                        return Response(
                            status_code=400,
                            content='{"error":"Invalid API path","request_id":"%s"}' % request_id,
                            media_type="application/json",
                            headers={"X-Request-ID": request_id, "X-Validation-Result": "rejected"},
                        )

            if request.method not in self._SAFE_METHODS:
                content_type = request.headers.get("Content-Type", "")
                if content_type and "application/json" not in content_type and "multipart/form-data" not in content_type:
                    _validation_error_reason.set("unsupported_media_type")
                    return Response(
                        status_code=415,
                        content='{"error":"Unsupported media type","request_id":"%s"}' % request_id,
                        media_type="application/json",
                        headers={"X-Request-ID": request_id, "X-Validation-Result": "rejected"},
                    )

            _validation_error_reason.set(None)
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Validation-Result"] = "accepted"
            return response

        except Exception:
            logger.exception("Unhandled exception in middleware pipeline for request %s", request_id)
            _validation_error_reason.set("internal_error")
            return Response(
                status_code=500,
                content='{"error":"Internal server error","request_id":"%s"}' % request_id,
                media_type="application/json",
                headers={"X-Request-ID": request_id, "X-Validation-Result": "error"},
            )

        finally:
            current_request_id.reset(token)
            _validation_error_reason.reset(error_token)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        request_id = current_request_id.get() or request.headers.get("X-Request-ID", "unknown")
        logger.info("req_start method=%s path=%s request_id=%s", request.method, request.url.path, request_id)

        try:
            response = await call_next(request)
            duration = time.time() - start
            logger.info(
                "req_end method=%s path=%s status=%d duration=%.3fs request_id=%s",
                request.method, request.url.path, response.status_code, duration, request_id,
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Duration-Ms"] = str(round(duration * 1000, 1))
            return response

        except Exception:
            duration = time.time() - start
            logger.exception(
                "req_exception method=%s path=%s duration=%.3fs request_id=%s",
                request.method, request.url.path, duration, request_id,
            )
            raise
