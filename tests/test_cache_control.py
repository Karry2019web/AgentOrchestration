"""Tests for CacheControlMiddleware — verifies Cache-Control headers on authenticated JSON responses."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from src.api.middleware import CacheControlMiddleware


@pytest.mark.asyncio
async def test_authenticated_json_response_gets_no_store():
    """Authenticated JSON responses should have Cache-Control: no-store."""
    app = AsyncMock()
    app.return_value = JSONResponse({"data": "secret"})

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents",
        "headers": [
            (b"authorization", b"Bearer some-token"),
            (b"content-type", b"application/json"),
        ],
    }
    request = Request(scope)
    middleware = CacheControlMiddleware(lambda: None)

    response = await middleware.dispatch(request, app)
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Pragma") == "no-cache"


@pytest.mark.asyncio
async def test_unauthenticated_request_unchanged():
    """Unauthenticated requests should not have Cache-Control added."""
    app = AsyncMock()
    app.return_value = JSONResponse({"public": "data"})

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [(b"content-type", b"application/json")],
    }
    request = Request(scope)
    middleware = CacheControlMiddleware(lambda: None)

    response = await middleware.dispatch(request, app)
    assert "cache-control" not in response.headers


@pytest.mark.asyncio
async def test_non_json_response_unchanged():
    """Non-JSON authenticated responses should not have Cache-Control added."""
    app = AsyncMock()
    app.return_value = Response(content="<html></html>", media_type="text/html")

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents",
        "headers": [
            (b"authorization", b"Bearer token"),
            (b"content-type", b"text/html"),
        ],
    }
    request = Request(scope)
    middleware = CacheControlMiddleware(lambda: None)

    response = await middleware.dispatch(request, app)
    assert "cache-control" not in response.headers


@pytest.mark.asyncio
async def test_session_cookie_triggers_no_store():
    """Requests with session cookies should also get Cache-Control: no-store."""
    app = AsyncMock()
    app.return_value = JSONResponse({"data": "session-data"})

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents",
        "headers": [
            (b"cookie", b"session=abc123"),
            (b"content-type", b"application/json"),
        ],
    }
    request = Request(scope)
    middleware = CacheControlMiddleware(lambda: None)

    response = await middleware.dispatch(request, app)
    assert response.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_error_path_gets_no_store():
    """Error responses from authenticated requests should also be protected."""
    app = AsyncMock()
    app.return_value = JSONResponse({"error": "not found"}, status_code=404)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents/unknown",
        "headers": [
            (b"authorization", b"Bearer token"),
            (b"content-type", b"application/json"),
        ],
    }
    request = Request(scope)
    middleware = CacheControlMiddleware(lambda: None)

    response = await middleware.dispatch(request, app)
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.status_code == 404
