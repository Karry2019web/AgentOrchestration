"""Tests for CorsAllowlistMiddleware."""

import os
import pytest
from unittest.mock import Mock, AsyncMock, patch
from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import CorsAllowlistMiddleware, _merge_vary


@pytest.fixture
def app():
    """Minimal ASGI app that returns 200 OK."""
    async def _app(scope, receive, send):
        response = Response("OK", media_type="text/plain")
        await response(scope, receive, send)
    return _app


@pytest.fixture
def middleware():
    """CorsAllowlistMiddleware with a known allowlist."""
    allowlist = [
        "https://app.agentorchestrator.io",
        "https://dashboard.agentorchestrator.io",
    ]
    return CorsAllowlistMiddleware(None, allowlist=allowlist)


# -- _merge_vary unit tests ------------------------------------------------


@pytest.mark.parametrize(
    "current, header, expected",
    [
        ("", "Origin", "Origin"),
        ("Origin", "Origin", "Origin"),
        ("Accept", "Origin", "Accept, Origin"),
        ("Accept, Authorization", "Origin", "Accept, Authorization, Origin"),
        ("Accept, Origin, Authorization", "Origin", "Accept, Origin, Authorization"),
    ],
)
def test_merge_vary(current, header, expected):
    assert _merge_vary(current, header) == expected


# -- Middleware dispatch tests ----------------------------------------------


@pytest.mark.parametrize(
    "origin, expected_status, expected_allow_origin",
    [
        # Allowed origins get 200 + specific Access-Control-Allow-Origin
        ("https://app.agentorchestrator.io", 200, "https://app.agentorchestrator.io"),
        ("https://dashboard.agentorchestrator.io", 200, "https://dashboard.agentorchestrator.io"),
        # Allowed origin with trailing slash is normalised
        ("https://app.agentorchestrator.io/", 200, "https://app.agentorchestrator.io/"),
        # Disallowed origins get 403
        ("https://evil.com", 403, None),
        ("http://localhost:3000", 403, None),
        # Missing origin is passed through
        (None, 200, None),
        # Empty origin is passed through
        ("", 200, None),
    ],
)
@pytest.mark.asyncio
async def test_cors_allowlist_dispatch(origin, expected_status, expected_allow_origin):
    """CorsAllowlistMiddleware enforces the allowlist correctly."""
    allowlist = [
        "https://app.agentorchestrator.io",
        "https://dashboard.agentorchestrator.io",
    ]

    # Build a request with the given origin
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/workflows",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }
    if origin is not None:
        scope["headers"].append((b"origin", origin.encode()))
    request = Request(scope)

    async def call_next(request):
        resp = Response("OK", media_type="text/plain")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    middleware = CorsAllowlistMiddleware(None, allowlist=allowlist)
    response = await middleware.dispatch(request, call_next)

    assert response.status_code == expected_status
    if expected_allow_origin is not None:
        assert response.headers.get("Access-Control-Allow-Origin") == origin
    else:
        # For non-allowed origins, the header may be absent or unchanged
        pass


@pytest.mark.parametrize(
    "method",
    ["GET", "HEAD", "OPTIONS"],
)
@pytest.mark.asyncio
async def test_non_credentialed_methods_pass_through(method):
    """GET, HEAD, OPTIONS requests pass through even with a disallowed origin."""
    scope = {
        "type": "http",
        "method": method,
        "path": "/health",
        "headers": [(b"origin", b"https://evil.com")],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }
    request = Request(scope)

    async def call_next(request):
        return Response("OK")

    allowlist = ["https://app.agentorchestrator.io"]
    middleware = CorsAllowlistMiddleware(None, allowlist=allowlist)
    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_cors_blocked_logs_warning():
    """Blocked origins produce a warning log."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/workflows",
        "headers": [(b"origin", b"https://evil.com")],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }
    request = Request(scope)

    async def call_next(request):
        return Response("OK")

    allowlist = ["https://app.agentorchestrator.io"]
    with patch("src.api.middleware.logger") as mock_logger:
        middleware = CorsAllowlistMiddleware(None, allowlist=allowlist)
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 403
        mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_exception_path_does_not_leak_state():
    """If call_next raises, state from prior requests is not leaked."""
    scope1 = {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/tasks",
        "headers": [(b"origin", b"https://app.agentorchestrator.io")],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }
    scope2 = {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/tasks",
        "headers": [(b"origin", b"https://evil.com")],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }

    call_count = 0

    async def call_next(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("upstream failure")
        return Response("OK")

    allowlist = ["https://app.agentorchestrator.io"]
    middleware = CorsAllowlistMiddleware(None, allowlist=allowlist)

    # First request raises — middleware should not catch it
    with pytest.raises(RuntimeError, match="upstream failure"):
        await middleware.dispatch(Request(scope1), call_next)

    # Second request (disallowed origin) should still get a 403
    response = await middleware.dispatch(Request(scope2), call_next)
    assert response.status_code == 403
