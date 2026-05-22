"""API middleware components."""

import time
import logging
from typing import Callable, Dict, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class WorkspaceContext:
    """Tracks authenticated workspace and role for the current request."""

    def __init__(self):
        self._token_store: Dict[str, Dict] = {}

    def register_token(self, token: str, workspace_id: str, role: str,
                       user_id: str) -> None:
        self._token_store[token] = {
            "workspace_id": workspace_id,
            "role": role,
            "user_id": user_id,
            "created_at": time.time(),
        }

    def validate(self, token: str, required_workspace: Optional[str] = None) -> Optional[Dict]:
        session = self._token_store.get(token)
        if not session:
            return None
        if required_workspace and session["workspace_id"] != required_workspace:
            return None
        return session

    def invalidate(self, token: str) -> None:
        self._token_store.pop(token, None)

    def is_member_of(self, token: str, workspace_id: str) -> bool:
        session = self._token_store.get(token)
        if not session:
            return False
        return session["workspace_id"] == workspace_id


workspace_context = WorkspaceContext()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized")

            token = auth_header.removeprefix("Bearer ")

            # Extract workspace from path or query
            workspace_id = request.headers.get("X-Workspace-Id")

            # Enforce workspace membership for saved view sharing endpoints
            if "/views/shared" in request.url.path and workspace_id:
                if not workspace_context.is_member_of(token, workspace_id):
                    logger.warning(
                        f"Rejected view sharing request: token not member of workspace {workspace_id}"
                    )
                    return Response(
                        status_code=403,
                        content="Forbidden: not a member of this workspace"
                    )

            # Validate session exists for protected endpoints
            session = workspace_context.validate(token, workspace_id)
            if not session and not request.url.path.startswith("/api/v2/auth/"):
                # Check if the token was ever registered
                if token:
                    # Token is present but not registered - could be stale or revoked
                    return Response(
                        status_code=401,
                        content="Unauthorized: invalid or expired credentials"
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
