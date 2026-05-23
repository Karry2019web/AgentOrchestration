"""API middleware components — auth scheme case-insensitive validation."""

import time
import re
import hashlib
import logging
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# RFC 7235 § 2.1: auth schemes are case-insensitive.
_BEARER_RE = re.compile(r"^[Bb][Ee][Aa][Rr][Ee][Rr]\s+(.+)$")

# Maximum age for a bearer token (seconds). Beyond this the token is stale.
_MAX_TOKEN_AGE = 7 * 24 * 3600  # 7 days

# Known stale/revoked token prefixes (first 8 chars of SHA-256 hash).
# Populated via environment variable AO_REVOKED_TOKENS (comma-separated SHA-256 prefixes).
_REVOKED_TOKEN_PREFIXES: set = set()


def _get_bearer_token(auth_header: str) -> Optional[str]:
    """Extract the token from an Authorization header, case-insensitively.

    Returns the token string or None if the header is missing, malformed, or
    uses an unsupported scheme.
    """
    if not auth_header:
        return None
    m = _BEARER_RE.match(auth_header)
    if not m:
        return None
    return m.group(1).strip()


def _is_token_stale(token: str) -> bool:
    """Check whether a token exceeds the maximum allowed age.

    Expects the token to embed a Unix timestamp as a colon suffix
    (e.g. ``tok_abc:1717000000``).  Tokens that don't embed a timestamp
    are assumed to be non-stale (pass through).
    """
    try:
        parts = token.rsplit(":", 1)
        if len(parts) < 2:
            return False
        ts = int(parts[-1])
        age = time.time() - ts
        return age > _MAX_TOKEN_AGE
    except (ValueError, IndexError):
        return False


def _is_token_revoked(token: str) -> bool:
    """Check whether the token's hash prefix is in the revoked set."""
    if not _REVOKED_TOKEN_PREFIXES:
        return False
    h = hashlib.sha256(token.encode()).hexdigest()[:8]
    return h in _REVOKED_TOKEN_PREFIXES


def configure_revoked_tokens(prefixes: str) -> None:
    """Load comma-separated SHA-256 prefixes from an env var value."""
    global _REVOKED_TOKEN_PREFIXES
    _REVOKED_TOKEN_PREFIXES = {p.strip() for p in prefixes.split(",") if p.strip()}


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates Bearer tokens with case-insensitive scheme matching.

    - Accepts ``Bearer``, ``bearer``, ``BEARER``, and any mixed-case variant
      per RFC 7235 § 2.1.
    - Rejects stale tokens (expired beyond ``_MAX_TOKEN_AGE``).
    - Rejects revoked tokens (SHA-256 prefix match against ``AO_REVOKED_TOKENS``).
    - Rejects anonymous / missing Authorization headers.
    - Bypasses the ``/api/v2/auth/token`` public endpoint.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Public endpoints — skip auth
        if request.url.path.startswith("/api/v2/auth/token"):
            return await call_next(request)

        # Only protect /api/v2 routes
        if not request.url.path.startswith("/api/v2"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        token = _get_bearer_token(auth_header)

        if token is None:
            # No valid Bearer token found — case mismatch, missing, or wrong scheme
            logger.warning("Auth rejected: missing or malformed Authorization header")
            return Response(
                status_code=401,
                content='{"error":"Unauthorized","detail":"Missing or malformed Bearer token. '
                        'Use a valid Authorization: Bearer <token> header (scheme is case-insensitive)."}',
                media_type="application/json",
            )

        if _is_token_stale(token):
            logger.warning("Auth rejected: stale token")
            return Response(
                status_code=401,
                content='{"error":"Unauthorized","detail":"Token has expired or is stale. '
                        'Request a fresh token."}',
                media_type="application/json",
            )

        if _is_token_revoked(token):
            logger.warning("Auth rejected: revoked token")
            return Response(
                status_code=403,
                content='{"error":"Forbidden","detail":"Token has been revoked."}',
                media_type="application/json",
            )

        # Attach token to request state for downstream handlers
        request.state.token = token
        request.state.auth_scheme = "Bearer"

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
