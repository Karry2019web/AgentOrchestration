"""API middleware components."""

import time
import logging
from typing import Callable, Dict, Optional, Set
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# Integration auth token store — tracks credential state for webhook management
class IntegrationAuthStore:
    """In-memory store for integration auth credential state.
    
    Tracks which API keys, tokens, or users have been disabled, revoked,
    or have expired credentials. Used by AuthMiddleware to reject stale
    credentials before any protected action is performed.
    """
    
    def __init__(self):
        self._disabled_users: Set[str] = set()
        self._revoked_tokens: Set[str] = set()
        self._expired_tokens: Dict[str, float] = {}
    
    def disable_user(self, user_id: str) -> None:
        self._disabled_users.add(user_id)
    
    def enable_user(self, user_id: str) -> None:
        self._disabled_users.discard(user_id)
    
    def is_user_disabled(self, user_id: str) -> bool:
        return user_id in self._disabled_users
    
    def revoke_token(self, token_hash: str) -> None:
        self._revoked_tokens.add(token_hash)
    
    def is_token_revoked(self, token_hash: str) -> bool:
        return token_hash in self._revoked_tokens
    
    def set_token_expiry(self, token_hash: str, expiry: float) -> None:
        self._expired_tokens[token_hash] = expiry
    
    def is_token_expired(self, token_hash: str) -> bool:
        if token_hash in self._expired_tokens:
            return time.time() > self._expired_tokens[token_hash]
        return False
    
    def is_credential_valid(self, user_id: str, token_hash: str) -> bool:
        """Check if a credential is fully valid: user enabled, token not revoked, token not expired."""
        if self.is_user_disabled(user_id):
            return False
        if self.is_token_revoked(token_hash):
            return False
        if self.is_token_expired(token_hash):
            return False
        return True


# Global integration auth store — shared across middleware instances
integration_auth_store = IntegrationAuthStore()


# Webhook management paths that require integration auth validation
WEBHOOK_MANAGEMENT_PATHS = [
    "/api/v2/webhooks",
    "/api/v2/integrations/webhook",
    "/api/v2/integrations",
]


def _is_webhook_management_path(path: str) -> bool:
    """Check if the request path is a webhook management endpoint."""
    for prefix in WEBHOOK_MANAGEMENT_PATHS:
        if path.startswith(prefix):
            return True
    return False


def _extract_user_id(token: str) -> Optional[str]:
    """Extract user ID from a Bearer token.
    
    In a real system this would validate JWT claims or decode the token.
    For this implementation, we parse a simple 'user:<user_id>' format
    embedded in the token payload.
    """
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            import json as _json
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
            payload = _json.loads(decoded)
            return payload.get("sub") or payload.get("user_id")
    except Exception:
        pass
    return None


def _hash_token(token: str) -> str:
    """Create a consistent hash of a token for store lookups."""
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized: Missing or malformed Authorization header")
            
            token = auth_header[len("Bearer "):]
            
            if _is_webhook_management_path(request.url.path):
                user_id = _extract_user_id(token)
                token_hash = _hash_token(token)
                
                if not user_id:
                    return Response(
                        status_code=401,
                        content="Unauthorized: Invalid token — could not extract identity"
                    )
                
                if integration_auth_store.is_user_disabled(user_id):
                    logger.warning(f"Blocked webhook management request from disabled user: {user_id}")
                    return Response(
                        status_code=403,
                        content="Forbidden: User account is disabled — webhook management access revoked"
                    )
                
                if integration_auth_store.is_token_revoked(token_hash):
                    logger.warning(f"Blocked webhook management request using revoked token for user: {user_id}")
                    return Response(
                        status_code=401,
                        content="Unauthorized: Token has been revoked — request a new API key"
                    )
                
                if integration_auth_store.is_token_expired(token_hash):
                    logger.warning(f"Blocked webhook management request using expired token for user: {user_id}")
                    return Response(
                        status_code=401,
                        content="Unauthorized: Token has expired — refresh your credentials"
                    )
        
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

# 2019-03-01T18:35:19 update

# 2019-04-03T13:22:05 update

# 2019-04-30T17:18:49 update

# 2019-08-20T09:29:03 update

# 2019-08-30T15:52:06 update

# 2019-11-23T16:58:42 update

# 2020-02-18T10:04:07 update

# 2020-04-21T17:35:30 update

# 2020-05-22T11:10:34 update

# 2020-07-02T12:31:26 update

# 2020-07-05T13:52:59 update

# 2020-08-21T20:36:45 update

# 2021-01-19T09:17:15 update

# 2021-01-29T11:34:24 update

# 2021-02-04T15:21:21 update

# 2021-04-19T19:23:15 update

# 2021-05-20T16:50:15 update

# 2021-06-22T19:23:44 update

# 2021-09-09T13:44:55 update

# 2021-09-16T09:30:20 update

# 2021-10-14T20:42:33 update

# 2021-12-28T16:39:14 update

# 2022-01-26T19:07:27 update

# 2022-01-28T08:03:41 update

# 2022-03-23T12:17:02 update

# 2022-04-06T12:12:27 update

# 2022-04-21T14:53:01 update

# 2022-06-30T08:37:32 update

# 2022-07-06T10:44:45 update

# 2022-11-02T11:12:47 update

# 2022-11-15T20:54:21 update

# 2022-11-23T14:13:34 update

# 2023-01-26T10:03:44 update

# 2023-02-09T17:08:10 update

# 2023-02-16T10:04:00 update

# 2023-03-14T11:52:03 update

# 2023-04-10T12:42:07 update

# 2023-04-26T10:43:39 update

# 2023-06-27T08:18:07 update

# 2023-08-30T15:30:40 update

# 2023-08-30T14:10:05 update

# 2023-10-09T18:32:46 update

# 2023-11-21T20:35:55 update

# 2024-03-07T19:17:39 update

# 2024-04-01T18:06:19 update

# 2024-07-18T15:37:34 update

# 2024-07-25T09:21:53 update

# 2024-08-12T14:24:22 update

# 2024-11-18T08:50:54 update

# 2025-04-08T12:43:05 update

# 2025-06-03T08:10:47 update

# 2025-06-12T08:37:52 update

# 2025-06-17T08:36:56 update

# 2025-07-02T18:09:42 update

# 2025-07-22T12:39:21 update

# 2025-10-13T12:13:46 update

# 2025-12-05T09:44:22 update

# 2025-12-22T18:34:47 update

# 2026-01-26T15:36:23 update

# 2026-02-13T12:36:40 update

# 2026-02-26T11:07:15 update

# 2026-03-19T11:00:17 update

# 2026-03-27T12:58:53 update

# 2026-05-12T17:19:36 update

# 2026-05-24T17:30:00 update
