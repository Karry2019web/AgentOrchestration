"""API middleware components."""

import re
import time
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# Maximum boundary length per RFC 2046 section 5.1.1 (70 chars max recommended)
_MAX_BOUNDARY_LENGTH = 70
# Valid boundary pattern: starts with ASCII letter/digit, contains only letters, digits, and +-_./ chars
_VALID_BOUNDARY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+\-._/]*$")


class MultipartBoundaryMiddleware(BaseHTTPMiddleware):
    """Validate multipart/form-data boundaries before the request body is buffered.

    Rejects requests with missing, blank, malformed, or overly long boundaries
    before the handler or downstream middleware can process them, preventing
    resource exhaustion from unbounded upload buffering.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            boundary = self._extract_boundary(content_type)
            error = self._validate_boundary(boundary)
            if error:
                logger.warning("Rejected multipart request: %s", error)
                return Response(status_code=400, content=error)
        return await call_next(request)

    @staticmethod
    def _extract_boundary(content_type: str) -> str | None:
        """Extract the boundary parameter from a Content-Type header."""
        # Parse boundary=... parameter, handling quoted values
        for part in content_type.split(";"):
            part = part.strip()
            if part.lower().startswith("boundary="):
                value = part[9:].strip()
                if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                return value
        return None

    @staticmethod
    def _validate_boundary(boundary: str | None) -> str | None:
        """Return an error message if the boundary is invalid, or None."""
        if boundary is None:
            return "Missing multipart boundary parameter"
        if not boundary:
            return "Blank multipart boundary"
        if len(boundary) > _MAX_BOUNDARY_LENGTH:
            return f"Boundary too long ({len(boundary)} chars, max {_MAX_BOUNDARY_LENGTH})"
        if not _VALID_BOUNDARY_RE.match(boundary):
            return f"Malformed boundary: starts with or contains invalid characters"
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
        response = await call_next(request)
        duration = time.time() - start
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")
        return response
