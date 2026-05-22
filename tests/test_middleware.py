"""Tests for API middleware authentication."""
import pytest
from unittest.mock import Mock, AsyncMock
from starlette.requests import Request
from starlette.responses import Response
from src.api.middleware import AuthMiddleware, classify_token


class TestTokenClassification:
    def test_machine_token_prefix(self):
        assert classify_token("mch_abc123") == "machine"

    def test_user_token_prefix(self):
        assert classify_token("usr_xyz789") == "user"

    def test_unrecognized_token(self):
        assert classify_token("tok_random") is None

    def test_empty_token(self):
        assert classify_token("") is None


class TestAuthMiddleware:
    @pytest.fixture
    def auth_middleware(self):
        return AuthMiddleware(app=Mock())

    @pytest.mark.asyncio
    async def test_missing_auth_header(self, auth_middleware):
        request = Mock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.headers = {}
        call_next = AsyncMock()

        response = await auth_middleware.dispatch(request, call_next)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_machine_token_read_allowed(self, auth_middleware):
        request = Mock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.method = "GET"
        request.headers = {"Authorization": "Bearer mch_token123"}
        call_next = AsyncMock(return_value=Response("OK", status_code=200))

        response = await auth_middleware.dispatch(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_machine_token_write_forbidden(self, auth_middleware):
        request = Mock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.method = "POST"
        request.headers = {"Authorization": "Bearer mch_token123"}
        call_next = AsyncMock()

        response = await auth_middleware.dispatch(request, call_next)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_user_token_write_allowed(self, auth_middleware):
        request = Mock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.method = "POST"
        request.headers = {"Authorization": "Bearer usr_token123"}
        call_next = AsyncMock(return_value=Response("OK", status_code=200))

        response = await auth_middleware.dispatch(request, call_next)
        assert response.status_code == 200
