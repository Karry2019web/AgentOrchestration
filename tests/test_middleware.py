"""Tests for API middleware components."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from src.api.middleware import ErrorSanitizationMiddleware


class TestErrorSanitizationMiddleware:
    """Test suite for ErrorSanitizationMiddleware."""

    @pytest.fixture
    def middleware(self):
        app = MagicMock()
        return ErrorSanitizationMiddleware(app)

    @pytest.mark.asyncio
    async def test_normal_request_passes_through(self, middleware):
        """Normal requests without exceptions should pass through unchanged."""
        mock_request = MagicMock(spec=Request, _state={})
        mock_request.state = MagicMock()
        mock_response = Response("OK", status_code=200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(mock_request, call_next)
        assert response.status_code == 200
        assert response.body == b"OK"

    @pytest.mark.asyncio
    async def test_exception_returns_generic_500(self, middleware):
        """Unhandled exceptions should return a generic 500 response."""
        mock_request = MagicMock(spec=Request, _state={})
        mock_request.state = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/api/v2/agents"

        async def call_next(req):
            raise ValueError("database connection failed - secret=abc123")

        response = await middleware.dispatch(mock_request, call_next)
        assert response.status_code == 500

        import json
        body = json.loads(response.body)
        assert body["detail"] == "Internal server error"
        # Verify sensitive details are NOT in the response
        assert "secret" not in response.body.decode()
        assert "database" not in response.body.decode()

    @pytest.mark.asyncio
    async def test_sanitized_header_added_on_error(self, middleware):
        """Error responses should include X-Error-Sanitized header."""
        mock_request = MagicMock(spec=Request, _state={})
        mock_request.state = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/v2/agents"

        async def call_next(req):
            raise RuntimeError("internal failure")

        response = await middleware.dispatch(mock_request, call_next)
        assert response.headers.get("X-Error-Sanitized") == "true"

    @pytest.mark.asyncio
    async def test_no_sanitized_header_on_normal(self, middleware):
        """Normal responses should NOT have the X-Error-Sanitized header."""
        mock_request = MagicMock(spec=Request, _state={})
        mock_request.state = MagicMock()

        async def call_next(req):
            return Response("OK", status_code=200)

        response = await middleware.dispatch(mock_request, call_next)
        assert "X-Error-Sanitized" not in response.headers

    @pytest.mark.asyncio
    async def test_request_local_state_cleaned_in_finally(self, middleware):
        """Request-local state should be cleaned up in finally block."""
        mock_request = MagicMock(spec=Request, _state={})
        mock_request.state = MagicMock()
        mock_request.state._sanitization_context = {"secret": "sensitive"}

        async def call_next(req):
            return Response("OK", status_code=200)

        await middleware.dispatch(mock_request, call_next)
        # After dispatch, the sanitization context should be removed
        assert not hasattr(mock_request.state, "_sanitization_context")

    @pytest.mark.asyncio
    async def test_state_cleaned_on_exception_path(self, middleware):
        """Request-local state should be cleaned even when exception occurs."""
        mock_request = MagicMock(spec=Request, _state={})
        mock_request.state = MagicMock()
        mock_request.state._sanitization_context = {"foo": "bar"}
        mock_request.method = "GET"
        mock_request.url.path = "/api/v2/test"

        async def call_next(req):
            raise Exception("boom")

        await middleware.dispatch(mock_request, call_next)
        assert not hasattr(mock_request.state, "_sanitization_context")

    @pytest.mark.asyncio
    async def test_no_state_no_error(self, middleware):
        """Dispatch should not fail when request has no state at all."""
        mock_request = MagicMock(spec=Request, _state={})
        mock_request.state = None

        async def call_next(req):
            return Response("OK", status_code=200)

        response = await middleware.dispatch(mock_request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_consecutive_requests_no_leak(self, middleware):
        """Multiple requests should not leak sanitization context between them."""
        async def good_handler(req):
            return Response("OK", status_code=200)

        async def bad_handler(req):
            raise ValueError("fail")

        # First request - fails
        req1 = MagicMock(spec=Request, _state={})
        req1.state = MagicMock()
        req1.state._sanitization_context = {"leak": "data"}
        req1.method = "GET"
        req1.url.path = "/api/v2/fail"

        await middleware.dispatch(req1, bad_handler)
        assert not hasattr(req1.state, "_sanitization_context")

        # Second request - succeeds
        req2 = MagicMock(spec=Request, _state={})
        req2.state = MagicMock()

        response = await middleware.dispatch(req2, good_handler)
        assert response.status_code == 200

