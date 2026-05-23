"""Tests for API middleware."""

import pytest
from src.api.middleware import AuthMiddleware


class TestAuthMiddleware:
    def test_token_requires_bearer_prefix(self):
        """Tokens without Bearer prefix should be rejected."""
        assert AuthMiddleware._parse_scopes("") == set()

    def test_admin_token_has_admin_scope(self):
        """Admin-prefixed tokens should have admin scope."""
        scopes = AuthMiddleware._parse_scopes("admin_abc123")
        assert "admin" in scopes

    def test_operator_token_has_operator_scope(self):
        """Operator-prefixed tokens should have operator scope."""
        scopes = AuthMiddleware._parse_scopes("op_def456")
        assert "operator" in scopes
        assert "admin" not in scopes

    def test_readonly_token_lacks_operator_scope(self):
        """Readonly-prefixed tokens should not have operator scope."""
        scopes = AuthMiddleware._parse_scopes("ro_ghi789")
        assert "operator" not in scopes
        assert "admin" not in scopes
        assert "readonly" in scopes

    def test_scope_map_requires_admin_for_delete(self):
        """Delete endpoints should require admin scope."""
        assert AuthMiddleware._SCOPE_MAP["delete"] == "admin"

    def test_scope_map_requires_operator_for_stop(self):
        """Stop endpoints should require operator scope."""
        assert AuthMiddleware._SCOPE_MAP["stop"] == "operator"
