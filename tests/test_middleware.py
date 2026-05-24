"""Tests for API middleware — bearer token parsing."""

import pytest
from unittest.mock import Mock, AsyncMock
from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import AuthMiddleware, _parse_bearer_token


class TestParseBearerToken:
    """_parse_bearer_token: validate auth scheme casing consistency."""

    def test_standard_bearer(self):
        """Standard 'Bearer <token>' is accepted."""
        assert _parse_bearer_token("Bearer abc123") == "abc123"

    def test_lowercase_bearer(self):
        """'bearer <token>' (lowercase) is accepted per RFC 7235."""
        assert _parse_bearer_token("bearer abc123") == "abc123"

    def test_uppercase_bearer(self):
        """'BEARER <token>' (uppercase) is accepted per RFC 7235."""
        assert _parse_bearer_token("BEARER abc123") == "abc123"

    def test_mixed_case_bearer(self):
        """'BeArEr <token>' (mixed case) is accepted per RFC 7235."""
        assert _parse_bearer_token("BeArEr abc123") == "abc123"

    def test_empty_header(self):
        """Empty header returns None."""
        assert _parse_bearer_token("") is None

    def test_missing_header(self):
        """None header returns None."""
        assert _parse_bearer_token(None) is None

    def test_malformed_no_space(self):
        """'Bearer' without space and token returns None."""
        assert _parse_bearer_token("Bearer") is None

    def test_malformed_no_token(self):
        """'Bearer ' without token returns None."""
        assert _parse_bearer_token("Bearer ") is None

    def test_wrong_scheme(self):
        """Non-Bearer schemes (e.g. Basic, Digest) return None."""
        assert _parse_bearer_token("Basic dXNlcjpwYXNz") is None
        assert _parse_bearer_token("Digest realm=test") is None

    def test_token_with_spaces(self):
        """Token is strictly the second whitespace-delimited part."""
        assert _parse_bearer_token("Bearer token123 extra") == "token123"


class TestAuthMiddlewareBearerCasing:
    """AuthMiddleware rejects unauthorized requests regardless of auth scheme casing."""

    @pytest.mark.asyncio
    async def test_rejects_no_auth(self):
        """Request without Authorization header returns 401."""
        middleware = AuthMiddleware(Mock())
        request = Mock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.headers = {}
        call_next = AsyncMock()
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 401
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_bearer(self):
        """Request with 'Bearer' header passes through."""
        middleware = AuthMiddleware(Mock())
        request = Mock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.headers = {"Authorization": "Bearer valid-token"}
        call_next = AsyncMock(return_value=Response(status_code=200))
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_accepts_lowercase_bearer(self):
        """Request with 'bearer' (lowercase) passes through."""
        middleware = AuthMiddleware(Mock())
        request = Mock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.headers = {"Authorization": "bearer valid-token"}
        call_next = AsyncMock(return_value=Response(status_code=200))
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_wrong_scheme(self):
        """Request with wrong auth scheme returns 401."""
        middleware = AuthMiddleware(Mock())
        request = Mock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        call_next = AsyncMock()
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 401
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_auth_token_endpoint(self):
        """Auth token endpoint is exempt from auth."""
        middleware = AuthMiddleware(Mock())
        request = Mock(spec=Request)
        request.url.path = "/api/v2/auth/token"
        request.headers = {}
        call_next = AsyncMock(return_value=Response(status_code=200))
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        call_next.assert_called_once()

