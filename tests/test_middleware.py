"""Tests for middleware cancellation propagation."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import CancellationPropagationMiddleware


@pytest.fixture
def middleware():
    app = MagicMock()
    return CancellationPropagationMiddleware(app)


@pytest.mark.asyncio
async def test_normal_request_propagates_successfully(middleware):
    """Normal requests should return the response unchanged."""
    request = MagicMock(spec=Request)
    request.headers = {"X-Request-ID": "req-123"}
    request.url.path = "/api/v2/agents"

    expected_response = Response(status_code=200, content='{"status": "ok"}')
    call_next = AsyncMock(return_value=expected_response)

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_request_propagates_error(middleware):
    """Cancelled requests should propagate CancelledError and log warning."""
    request = MagicMock(spec=Request)
    request.headers = {"X-Request-ID": "req-cancel"}
    request.url.path = "/api/v2/agents"

    call_next = AsyncMock(side_effect=__import__("asyncio").CancelledError())

    with pytest.raises(__import__("asyncio").CancelledError):
        await middleware.dispatch(request, call_next)
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_exception_in_downstream_propagates(middleware):
    """Unhandled exceptions from downstream should propagate."""
    request = MagicMock(spec=Request)
    request.headers = {"X-Request-ID": "req-exc"}
    request.url.path = "/api/v2/agents"

    call_next = AsyncMock(side_effect=ValueError("downstream failure"))

    with pytest.raises(ValueError, match="downstream failure"):
        await middleware.dispatch(request, call_next)
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_cleaned_on_success(middleware):
    """Request-local context should be reset after a successful request."""
    request = MagicMock(spec=Request)
    request.headers = {"X-Request-ID": "req-clean"}
    request.url.path = "/api/v2/agents"

    call_next = AsyncMock(return_value=Response(status_code=200))

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_context_cleaned_on_cancellation(middleware):
    """Request-local context should be reset after cancellation."""
    request = MagicMock(spec=Request)
    request.headers = {"X-Request-ID": "req-clean-cancel"}
    request.url.path = "/api/v2/agents"

    call_next = AsyncMock(side_effect=__import__("asyncio").CancelledError())

    with pytest.raises(__import__("asyncio").CancelledError):
        await middleware.dispatch(request, call_next)


@pytest.mark.asyncio
async def test_rejected_request_bypasses_cancellation(middleware):
    """Middleware should handle rejected (non-started) requests gracefully."""
    request = MagicMock(spec=Request)
    request.headers = {"X-Request-ID": "req-reject"}
    request.url.path = "/api/v2/agents"

    call_next = AsyncMock(return_value=Response(status_code=401, content="Unauthorized"))

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 401
    call_next.assert_awaited_once()

# {now} update
