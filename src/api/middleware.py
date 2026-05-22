"""API middleware components."""

import time
import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# Machine tokens typically have a machine/ prefix or specific format
MACHINE_TOKEN_PREFIX = "mch_"
USER_TOKEN_PREFIX = "usr_"


def classify_token(token: str) -> Optional[str]:
    """Classify a token as machine or user based on its prefix.
    
    Returns 'machine', 'user', or None if unclassifiable.
    """
    if token.startswith(MACHINE_TOKEN_PREFIX):
        return "machine"
    elif token.startswith(USER_TOKEN_PREFIX):
        return "user"
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized: missing Bearer token")

            token = auth_header[len("Bearer "):]
            token_type = classify_token(token)

            if token_type is None:
                return Response(status_code=401, content="Unauthorized: unrecognized token format")

            # Machine tokens cannot perform user-scoped operations
            if token_type == "machine":
                # Only allow read operations for machine tokens
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    return Response(status_code=403, content="Forbidden: machine tokens cannot mutate state")

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
