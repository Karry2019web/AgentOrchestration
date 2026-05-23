"""Authentication and authorization service with role-based access control."""

import os
import time
import hmac
import hashlib
import base64
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Set, List, Dict
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


class UserRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class Permission(str, Enum):
    READ_AGENTS = "agents:read"
    CREATE_AGENTS = "agents:create"
    DELETE_AGENTS = "agents:delete"
    START_AGENTS = "agents:start"
    STOP_AGENTS = "agents:stop"
    CLONE_TEMPLATES = "templates:clone"
    MANAGE_TEMPLATES = "templates:manage"
    MANAGE_USERS = "users:manage"
    VIEW_AUDIT = "audit:view"


# Permission matrix: which role has which permissions
ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
    UserRole.ADMIN: {
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.DELETE_AGENTS,
        Permission.START_AGENTS,
        Permission.STOP_AGENTS,
        Permission.CLONE_TEMPLATES,
        Permission.MANAGE_TEMPLATES,
        Permission.MANAGE_USERS,
        Permission.VIEW_AUDIT,
    },
    UserRole.OPERATOR: {
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.START_AGENTS,
        Permission.STOP_AGENTS,
        Permission.CLONE_TEMPLATES,
    },
    UserRole.DEVELOPER: {
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.CLONE_TEMPLATES,
    },
    UserRole.VIEWER: {
        Permission.READ_AGENTS,
    },
}


@dataclass
class User:
    """Authenticated user with role and permissions."""
    id: str
    username: str
    role: UserRole
    token_type: str
    scopes: Set[str]

    def has_permission(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


# In-memory token -> user mapping
_ADMIN_TOKEN = os.getenv("AO_ADMIN_TOKEN", "ao-admin-token-dev")
_MACHINE_TOKENS: Dict[str, User] = {
    os.getenv("AO_MACHINE_TOKEN", "ao-machine-token-dev"): User(
        id="machine-1",
        username="ci-bot",
        role=UserRole.OPERATOR,
        token_type="machine",
        scopes={"agents:read", "agents:create", "templates:clone"},
    ),
}

_USER_TOKENS: Dict[str, User] = {
    "dev-token-admin": User(
        id="user-admin", username="admin",
        role=UserRole.ADMIN, token_type="bearer", scopes=set(),
    ),
    "dev-token-operator": User(
        id="user-operator", username="operator",
        role=UserRole.OPERATOR, token_type="bearer", scopes=set(),
    ),
    "dev-token-developer": User(
        id="user-developer", username="developer",
        role=UserRole.DEVELOPER, token_type="bearer", scopes=set(),
    ),
    "dev-token-viewer": User(
        id="user-viewer", username="viewer",
        role=UserRole.VIEWER, token_type="bearer", scopes=set(),
    ),
}


def validate_token(token_value: str) -> Optional[User]:
    """Validate a bearer token and return the associated user."""
    if token_value in _MACHINE_TOKENS:
        return _MACHINE_TOKENS[token_value]

    if token_value in _USER_TOKENS:
        return _USER_TOKENS[token_value]

    if token_value == _ADMIN_TOKEN:
        return User(
            id="admin-bootstrap", username="admin",
            role=UserRole.ADMIN, token_type="bearer", scopes=set(),
        )

    # HMAC-signed token validation
    try:
        parts = token_value.split(".")
        if len(parts) == 2:
            payload_b64, signature = parts
            expected = hmac.new(
                _ADMIN_TOKEN.encode(),
                payload_b64.encode(),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(signature, expected):
                padded = payload_b64 + "=="
                decoded = base64.b64decode(padded).decode()
                import json as _json
                data = _json.loads(decoded)
                return User(
                    id=data.get("sub", "unknown"),
                    username=data.get("name", "unknown"),
                    role=UserRole(data.get("role", "viewer")),
                    token_type="bearer",
                    scopes=set(data.get("scopes", [])),
                )
    except Exception:
        pass

    return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    """Extract and validate the current user from the Authorization header."""
    if credentials is None:
        return None

    user = validate_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(minimum_role: UserRole):
    """Dependency factory: returns a dependency that enforces a minimum role."""
    role_hierarchy = {
        UserRole.VIEWER: 0,
        UserRole.DEVELOPER: 1,
        UserRole.OPERATOR: 2,
        UserRole.ADMIN: 3,
    }

    async def _role_checker(
        user: Optional[User] = Depends(get_current_user),
    ) -> User:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if role_hierarchy.get(user.role, -1) < role_hierarchy.get(minimum_role, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions. "
                    f"Required role: {minimum_role.value}, "
                    f"current role: {user.role.value}"
                ),
            )
        return user

    return _role_checker


def require_permission(permission: Permission):
    """Dependency factory: returns a dependency that enforces a specific permission."""
    async def _permission_checker(
        user: Optional[User] = Depends(get_current_user),
    ) -> User:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions. "
                    f"Required permission: {permission.value}, "
                    f"current role: {user.role.value}"
                ),
            )
        return user

    return _permission_checker
