"""Tests for SSE compression limit middleware."""

import pytest
from unittest.mock import Mock, AsyncMock
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from src.api.middleware import CompressionLimitMiddleware, SSE_CONTENT_TYPE


@pytest.fixture
def middleware():
    app = Mock(spec=ASGIApp)
    return CompressionLimitMiddleware(app)


def make_request(accept_header: str = "*/*") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents/stream",
        "headers": [
            (b"accept", accept_header.encode()),
            (b"host", b"localhost"),
        ],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_normal_request_passes_through(middleware):
    """Normal requests should pass through without SSE headers."""
    call_next = AsyncMock(return_value=Response("ok", media_type="application/json"))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents",
        "headers": [(b"accept", b"application/json"), (b"host", b"localhost")],
    }
    request = Request(scope)
    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    assert response.body == b"ok"
    accept_encoding = response.headers.get("content-encoding", "")
    assert accept_encoding == "", "Normal request should not have content-encoding"


@pytest.mark.asyncio
async def test_sse_request_gets_no_cache_headers(middleware):
    """SSE requests should get no-cache and no-buffering headers."""
    call_next = AsyncMock(return_value=Response(
        "data: hello\n\n",
        media_type=SSE_CONTENT_TYPE,
        headers={"content-type": SSE_CONTENT_TYPE},
    ))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents/events",
        "headers": [(b"accept", SSE_CONTENT_TYPE.encode()), (b"host", b"localhost")],
    }
    request = Request(scope)
    response = await middleware.dispatch(request, call_next)
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-accel-buffering") == "no"
    assert response.headers.get("content-encoding") == "identity"


@pytest.mark.asyncio
async def test_sse_response_content_type_gets_identity_encoding(middleware):
    """Responses with SSE content-type should get identity encoding."""
    call_next = AsyncMock(return_value=Response(
        "data: test\n\n",
        media_type=SSE_CONTENT_TYPE,
        headers={"content-type": SSE_CONTENT_TYPE},
    ))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents/status",
        "headers": [(b"accept", b"*/*"), (b"host", b"localhost")],
    }
    request = Request(scope)
    response = await middleware.dispatch(request, call_next)
    assert response.headers.get("content-encoding") == "identity"
    assert response.headers.get("x-accel-buffering") == "no"


@pytest.mark.asyncio
async def test_exception_path_does_not_leak_state(middleware):
    """If call_next raises, middleware should not add SSE headers."""
    call_next = AsyncMock(side_effect=RuntimeError("stream error"))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents/events",
        "headers": [(b"accept", SSE_CONTENT_TYPE.encode()), (b"host", b"localhost")],
    }
    request = Request(scope)
    with pytest.raises(RuntimeError, match="stream error"):
        await middleware.dispatch(request, call_next)


@pytest.mark.asyncio
async def test_rejected_request_logs_no_leak(middleware):
    """Middleware should not set headers on rejected requests."""
    call_next = AsyncMock(return_value=Response(status_code=401, content="Unauthorized"))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents/events",
        "headers": [(b"accept", SSE_CONTENT_TYPE.encode()), (b"host", b"localhost")],
    }
    request = Request(scope)
    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 401
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-accel-buffering") == "no"
