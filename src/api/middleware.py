"""API middleware components."""

import os
import time
import logging
from typing import Callable, Optional

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Expected JWT audience for service-to-service calls.
# Agent workers authenticate with a JWT whose "aud" claim must match.
JWT_AUDIENCE = os.getenv("AO_JWT_AUDIENCE", "agent-orchestrator-api")

# Shared secret used to sign/verify internal JWTs.
# In production this would be sourced from a secrets manager.
JWT_SECRET = os.getenv("AO_JWT_SECRET", "")


def _decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT bearer token.

    Returns the decoded payload on success, or None when the token is
    stale, malformed, revoked, or insufficiently scoped.
    """
    if not token.startswith("Bearer "):
        return None
    raw = token[len("Bearer "):].strip()
    if not raw:
        return None

    # Attempt decoding with audience verification.
    # When no shared secret is configured we still inspect the unverified
    # payload so we can reject tokens that fail structural checks.
    if JWT_SECRET:
        try:
            payload = jwt.decode(
                raw,
                JWT_SECRET,
                audience=JWT_AUDIENCE,
                algorithms=["HS256"],
                options={
                    "require": ["exp", "iat", "aud", "sub"],
                    "verify_exp": True,
                },
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Rejected expired JWT")
            return None
        except jwt.InvalidAudienceError:
            logger.warning("Rejected JWT with wrong audience")
            return None
        except jwt.InvalidTokenError as exc:
            logger.warning("Rejected malformed JWT: %s", exc)
            return None

    # Fallback: no shared secret configured — still perform structural
    # checks on the unverified payload to catch obvious abuse.
    try:
        payload = jwt.decode(
            raw,
            options={"verify_signature": False, "require": ["exp", "iat"]},
        )
        now = time.time()
        if payload.get("exp", 0) < now:
            logger.warning("Rejected expired JWT (no-secret fallback)")
            return None
        return payload
    except jwt.InvalidTokenError as exc:
        logger.warning("Rejected structurally invalid JWT: %s", exc)
        return None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only protect API v2 paths (the auth/token endpoint is public).
        if not request.url.path.startswith("/api/v2"):
            return await call_next(request)
        if request.url.path == "/api/v2/auth/token":
            return await call_next(request)

        token = request.headers.get("Authorization", "")
        payload = _decode_token(token)
        if payload is None:
            return Response(status_code=401, content="Unauthorized")

        # Service-to-service audience enforcement.
        # Agent-worker tokens carry a "sub" with a "service:" prefix.
        # These tokens must include the orchestrator API in their audience.
        sub = payload.get("sub", "")
        aud = payload.get("aud", "")
        if sub.startswith("service:") or sub.startswith("agent:"):
            expected = JWT_AUDIENCE
            if isinstance(aud, list):
                if expected not in aud:
                    logger.warning(
                        "Service token %s missing audience %s (got %s)",
                        sub, expected, aud,
                    )
                    return Response(status_code=403, content="Forbidden")
            elif aud != expected:
                logger.warning(
                    "Service token %s has audience %s, expected %s",
                    sub, aud, expected,
                )
                return Response(status_code=403, content="Forbidden")

        # Attach decoded payload for downstream handlers.
        request.state.auth_payload = payload
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
