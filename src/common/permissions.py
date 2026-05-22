"""Authentication and authorization module — project role enforcement for secret metadata API."""

import time
from typing import Any, Dict, Optional
from dataclasses import dataclass, field


ROLE_HIERARCHY = {
    "viewer": 0,
    "developer": 1,
    "admin": 2,
    "owner": 3,
}


@dataclass
class ProjectRole:
    project_id: str
    role: str
    user_id: str
    issued_at: float = 0.0
    expires_at: float = 0.0

    @property
    def is_valid(self) -> bool:
        if self.expires_at > 0 and time.time() > self.expires_at:
            return False
        return True

    @property
    def level(self) -> int:
        return ROLE_HIERARCHY.get(self.role, -1)

    def can_read_environment_variables(self) -> bool:
        # Only developer+ can read environment variables
        return self.level >= ROLE_HIERARCHY["developer"] and self.is_valid


class AuthorizationService:
    """Central authorization service for project-scoped access control."""

    def __init__(self):
        self._token_store: Dict[str, str] = {}
        self._role_cache: Dict[str, ProjectRole] = {}

    def register_token(self, api_key: str, project_id: str) -> None:
        self._token_store[api_key] = project_id

    def validate_token(self, token: str) -> Optional[str]:
        """Validate a bearer token and return the associated project_id, or None if invalid."""
        return self._token_store.get(token)

    def get_role(self, user_id: str, project_id: str) -> Optional[ProjectRole]:
        return self._role_cache.get(f"{user_id}:{project_id}")

    def set_role(self, user_id: str, project_id: str, role: str, ttl: int = 3600) -> ProjectRole:
        now = time.time()
        pr = ProjectRole(
            project_id=project_id,
            role=role,
            user_id=user_id,
            issued_at=now,
            expires_at=now + ttl,
        )
        self._role_cache[f"{user_id}:{project_id}"] = pr
        return pr

    def invalidate_role(self, user_id: str, project_id: str) -> None:
        self._role_cache.pop(f"{user_id}:{project_id}", None)

    def check_environment_read_access(self, token: str) -> bool:
        """Enforce project role on environment variable reads — secret metadata API."""
        project_id = self.validate_token(token)
        if project_id is None:
            return False

        # Extract user_id from token (simplified — real impl would decode JWT)
        user_id = f"user:{token[:8]}"

        role = self.get_role(user_id, project_id)
        if role is None:
            # Role not cached — treat as unauthenticated
            return False

        if not role.is_valid:
            self.invalidate_role(user_id, project_id)
            return False

        return role.can_read_environment_variables()

    def enforce_environment_read(self, token: str) -> None:
        """Raise PermissionError if the principal lacks environment read access."""
        if not self.check_environment_read_access(token):
            raise PermissionError(
                "Insufficient project role: environment variable reads require at least developer role"
            )


# Global authorization service instance
authz_service = AuthorizationService()
