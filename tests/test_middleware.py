"""Tests for API middleware components."""

import pytest
from starlette.requests import Request
from starlette.responses import Response
from unittest.mock import AsyncMock, MagicMock
from src.api.middleware import (
    AuthMiddleware,
    validate_token,
    authorize,
)


class TestValidateToken:
    def test_missing_auth_header(self):
        is_valid, reason, _ = validate_token("")
        assert not is_valid
        assert reason == "missing_auth_header"

    def test_empty_token(self):
        is_valid, reason, _ = validate_token("Bearer ")
        assert not is_valid
        assert reason == "empty_token"

    def test_no_bearer_prefix(self):
        is_valid, reason, _ = validate_token("Basic abc123")
        assert not is_valid
        assert reason == "missing_auth_header"

    def test_valid_machine_token(self):
        is_valid, ttype, principal = validate_token("Bearer mch_abc123.def456ghijklmnop")
        assert is_valid
        assert ttype == "machine"
        assert principal == "mch_abc123.def456ghijklmnop"

    def test_short_machine_token(self):
        is_valid, reason, _ = validate_token("Bearer mch_abc.def")
        assert not is_valid
        assert reason == "malformed_machine_token"

    def test_valid_user_token(self):
        is_valid, ttype, principal = validate_token("Bearer usr_user99.signature12345678")
        assert is_valid
        assert ttype == "user"
        assert principal == "usr_user99.signature12345678"

    def test_short_user_token(self):
        is_valid, reason, _ = validate_token("Bearer usr_x.y")
        assert not is_valid
        assert reason == "malformed_user_token"

    def test_unknown_token_prefix(self):
        is_valid, reason, _ = validate_token("Bearer svc_abc123.def456")
        assert not is_valid
        assert reason == "unknown_token_type"

    def test_machine_token_no_dot(self):
        is_valid, reason, _ = validate_token("Bearer mch_abcdefghijklmnop")
        assert not is_valid
        assert reason == "malformed_machine_token"

    def test_user_token_no_dot(self):
        is_valid, reason, _ = validate_token("Bearer usr_abcdefghijklmnop")
        assert not is_valid
        assert reason == "malformed_user_token"


class TestAuthorize:
    def test_health_always_allowed(self):
        assert authorize("machine", "GET", "/health") == (True, "")
        assert authorize("user", "GET", "/health") == (True, "")

    def test_machine_can_create_agents(self):
        assert authorize("machine", "POST", "/api/v2/agents") == (True, "")

    def test_machine_can_delete_agents(self):
        assert authorize("machine", "DELETE", "/api/v2/agents") == (True, "")

    def test_machine_can_read_agents(self):
        assert authorize("machine", "GET", "/api/v2/agents") == (True, "")

    def test_user_can_read_agents(self):
        assert authorize("user", "GET", "/api/v2/agents") == (True, "")
        assert authorize("user", "GET", "/api/v2/agents/abc123") == (True, "")

    def test_user_cannot_create_agents(self):
        result, reason = authorize("user", "POST", "/api/v2/agents")
        assert not result
        assert reason == "user_tokens_are_read_only_for_agents"

    def test_user_cannot_delete_agents(self):
        result, reason = authorize("user", "DELETE", "/api/v2/agents/abc")
        assert not result
        assert reason == "user_tokens_are_read_only_for_agents"

    def test_machine_cannot_manage_user_auth(self):
        result, reason = authorize("machine", "POST", "/api/v2/auth/token")
        assert not result
        assert reason == "machine_tokens_cannot_manage_user_auth"

    def test_user_can_manage_own_auth(self):
        assert authorize("user", "POST", "/api/v2/auth/token") == (True, "")

    def test_unknown_endpoint_allowed_for_both(self):
        assert authorize("machine", "GET", "/api/v2/metrics") == (True, "")
        assert authorize("user", "GET", "/api/v2/metrics") == (True, "")


class TestAuthMiddleware:
    @pytest.fixture
    def mock_app(self):
        app = AsyncMock()
        app.return_value = Response(status_code=200, content="OK")
        return app

    @pytest.fixture
    def middleware(self, mock_app):
        return AuthMiddleware(mock_app)

    def _make_request(self, path, method="GET", token=None):
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "state": MagicMock(),
        }
        if token:
            scope["headers"].append((b"authorization", token.encode()))
        return Request(scope)

    def test_non_api_path_allowed(self, middleware):
        req = self._make_request("/health", "GET")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 200

    def test_no_auth_header_returns_401(self, middleware):
        req = self._make_request("/api/v2/agents", "GET")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 401
        assert "missing_auth_header" in resp.body.decode()

    def test_valid_machine_token_allowed(self, middleware):
        req = self._make_request("/api/v2/agents", "GET",
                                token="Bearer mch_deploy.abcdef1234567890")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 200

    def test_valid_machine_token_create_agent(self, middleware):
        req = self._make_request("/api/v2/agents", "POST",
                                token="Bearer mch_deploy.abcdef1234567890")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 200

    def test_user_token_read_agent_allowed(self, middleware):
        req = self._make_request("/api/v2/agents", "GET",
                                token="Bearer usr_user1.signature1234567890")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 200

    def test_user_token_create_agent_denied(self, middleware):
        req = self._make_request("/api/v2/agents", "POST",
                                token="Bearer usr_user1.signature1234567890")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 403
        assert "insufficient permissions" in resp.body.decode()

    def test_user_token_delete_agent_denied(self, middleware):
        req = self._make_request("/api/v2/agents/abc123", "DELETE",
                                token="Bearer usr_user1.signature1234567890")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 403

    def test_unknown_token_type_denied(self, middleware):
        req = self._make_request("/api/v2/agents", "GET",
                                token="Bearer svc_token.abcdef1234567890")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 401
        assert "unknown_token_type" in resp.body.decode()

    def test_malformed_token_denied(self, middleware):
        req = self._make_request("/api/v2/agents", "GET",
                                token="Bearer mch_short")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 401

    def test_auth_token_endpoint_exempt(self, middleware):
        req = self._make_request("/api/v2/auth/token", "POST")
        resp = middleware.dispatch(req, lambda r: Response(status_code=200))
        assert resp.status_code == 200
