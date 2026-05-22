"""Tests for middleware workspace membership enforcement."""

import pytest
from starlette.requests import Request
from starlette.responses import Response
from src.api.middleware import workspace_context


class TestWorkspaceContext:
    def setup_method(self):
        # Reset token store
        workspace_context._token_store = {}

    def test_register_and_validate(self):
        workspace_context.register_token("tok-1", "ws-1", "admin", "user-1")
        session = workspace_context.validate("tok-1")
        assert session is not None
        assert session["workspace_id"] == "ws-1"
        assert session["role"] == "admin"

    def test_validate_with_required_workspace(self):
        workspace_context.register_token("tok-2", "ws-2", "editor", "user-2")
        session = workspace_context.validate("tok-2", "ws-2")
        assert session is not None
        session = workspace_context.validate("tok-2", "ws-wrong")
        assert session is None

    def test_is_member_of(self):
        workspace_context.register_token("tok-3", "ws-3", "viewer", "user-3")
        assert workspace_context.is_member_of("tok-3", "ws-3") is True
        assert workspace_context.is_member_of("tok-3", "ws-other") is False

    def test_invalidate(self):
        workspace_context.register_token("tok-4", "ws-4", "admin", "user-4")
        assert workspace_context.validate("tok-4") is not None
        workspace_context.invalidate("tok-4")
        assert workspace_context.validate("tok-4") is None

    def test_stale_token_rejected(self):
        workspace_context.register_token("tok-5", "ws-5", "admin", "user-5")
        assert workspace_context.is_member_of("nonexistent", "ws-5") is False
