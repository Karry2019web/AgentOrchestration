"""Tests for authentication and authorization module."""

import pytest
from unittest.mock import patch, MagicMock

from src.api.auth import (
    User, UserRole, Permission, validate_token,
    ROLE_PERMISSIONS,
)


class TestRolePermissions:
    """Verify the permission matrix for each role."""

    def test_admin_has_all_permissions(self):
        perms = ROLE_PERMISSIONS[UserRole.ADMIN]
        assert Permission.READ_AGENTS in perms
        assert Permission.CREATE_AGENTS in perms
        assert Permission.DELETE_AGENTS in perms
        assert Permission.START_AGENTS in perms
        assert Permission.STOP_AGENTS in perms
        assert Permission.CLONE_TEMPLATES in perms
        assert Permission.MANAGE_TEMPLATES in perms
        assert Permission.MANAGE_USERS in perms
        assert Permission.VIEW_AUDIT in perms

    def test_operator_has_clone_permission(self):
        perms = ROLE_PERMISSIONS[UserRole.OPERATOR]
        assert Permission.CLONE_TEMPLATES in perms
        assert Permission.READ_AGENTS in perms
        assert Permission.CREATE_AGENTS in perms
        assert Permission.START_AGENTS in perms
        assert Permission.STOP_AGENTS in perms

    def test_operator_cannot_delete_or_manage(self):
        perms = ROLE_PERMISSIONS[UserRole.OPERATOR]
        assert Permission.DELETE_AGENTS not in perms
        assert Permission.MANAGE_USERS not in perms

    def test_developer_has_clone_permission(self):
        perms = ROLE_PERMISSIONS[UserRole.DEVELOPER]
        assert Permission.CLONE_TEMPLATES in perms
        assert Permission.READ_AGENTS in perms
        assert Permission.CREATE_AGENTS in perms

    def test_developer_cannot_start_stop_agents(self):
        perms = ROLE_PERMISSIONS[UserRole.DEVELOPER]
        assert Permission.START_AGENTS not in perms
        assert Permission.STOP_AGENTS not in perms
        assert Permission.DELETE_AGENTS not in perms

    def test_viewer_only_read(self):
        perms = ROLE_PERMISSIONS[UserRole.VIEWER]
        assert Permission.READ_AGENTS in perms
        assert Permission.CLONE_TEMPLATES not in perms
        assert Permission.CREATE_AGENTS not in perms

    def test_user_has_permission_method(self):
        admin = User(id="a", username="admin", role=UserRole.ADMIN,
                     token_type="bearer", scopes=set())
        assert admin.has_permission(Permission.CLONE_TEMPLATES)
        assert admin.has_permission(Permission.DELETE_AGENTS)

    def test_viewer_lacks_clone_permission(self):
        viewer = User(id="v", username="viewer", role=UserRole.VIEWER,
                      token_type="bearer", scopes=set())
        assert not viewer.has_permission(Permission.CLONE_TEMPLATES)


class TestTokenValidation:
    """Verify token validation logic."""

    def test_dev_admin_token(self):
        user = validate_token("dev-token-admin")
        assert user is not None
        assert user.role == UserRole.ADMIN
        assert user.username == "admin"

    def test_dev_operator_token(self):
        user = validate_token("dev-token-operator")
        assert user is not None
        assert user.role == UserRole.OPERATOR
        assert user.username == "operator"

    def test_dev_developer_token(self):
        user = validate_token("dev-token-developer")
        assert user is not None
        assert user.role == UserRole.DEVELOPER
        assert user.username == "developer"

    def test_dev_viewer_token(self):
        user = validate_token("dev-token-viewer")
        assert user is not None
        assert user.role == UserRole.VIEWER
        assert user.username == "viewer"

    def test_invalid_token_returns_none(self):
        user = validate_token("invalid-token-12345")
        assert user is None

    def test_empty_token_returns_none(self):
        user = validate_token("")
        assert user is None

    def test_machine_token(self):
        # The machine token is set to "ao-machine-token-dev" by default
        user = validate_token("ao-machine-token-dev")
        assert user is not None
        assert user.role == UserRole.OPERATOR
        assert user.token_type == "machine"

    def test_admin_bootstrap_token(self):
        user = validate_token("ao-admin-token-dev")
        assert user is not None
        assert user.role == UserRole.ADMIN
        assert user.username == "admin"


class TestHMACToken:
    """Verify HMAC-signed token validation."""

    def test_hmac_token_validation(self):
        import hmac, hashlib, base64, json as _json
        payload = _json.dumps({"sub": "user-1", "name": "hmac-user", "role": "developer", "scopes": ["templates:clone"]})
        payload_b64 = base64.b64encode(payload.encode()).decode().rstrip("=")
        signature = hmac.new(
            b"ao-admin-token-dev",
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()
        token = f"{payload_b64}.{signature}"

        user = validate_token(token)
        assert user is not None
        assert user.username == "hmac-user"
        assert user.role == UserRole.DEVELOPER
        assert user.has_permission(Permission.CLONE_TEMPLATES)


class TestUserDataclass:
    """Verify User helper methods."""

    def test_has_scope(self):
        user = User(id="u1", username="test", role=UserRole.DEVELOPER,
                    token_type="bearer", scopes={"agents:read"})
        assert user.has_scope("agents:read")
        assert not user.has_scope("agents:write")

    def test_empty_scopes(self):
        user = User(id="u1", username="test", role=UserRole.VIEWER,
                    token_type="bearer", scopes=set())
        assert not user.has_scope("anything")
