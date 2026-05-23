"""Tests for API middleware components."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request
from starlette.responses import Response
from starlette.datastructures import Headers, URL, State
from starlette.types import ASGIApp, Receive, Scope, Send

from src.api.middleware import (
    AuthMiddleware,
    RateLimitMiddleware,
    LoggingMiddleware,
    CancellationPropagationMiddleware,
)


class MockASGIApp:
    """Minimal ASGI app that returns a fixed response."""
    def __init__(self, response: Response = None, delay: float = 0.0, raise_cancelled: bool = False):
        self.response = response or Response(status_code=200, content="OK")
        self.delay = delay
        self.raise_cancelled = raise_cancelled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_cancelled:
            raise asyncio.CancelledError()
        await self.response(scope, receive, send)


@pytest.fixture
def mock_request():
    """Create a minimal Starlette Request for testing."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents",
        "headers": [(b"host", b"testserver")],
        "query_string": b"",
        "client": ("127.0.0.1", 50000),
        "state": {},
    }
    request = Request(scope)
    request.state = State()
    return request


class TestCancellationPropagationMiddleware:
    """Verify cancellation propagation to downstream agent calls."""

    @pytest.mark.asyncio
    async def test_normal_request_passes_through(self, mock_request):
        """Middleware should pass through normal requests unchanged."""
        app = MockASGIApp(Response(status_code=200, content="OK"))
        middleware = CancellationPropagationMiddleware(app)

        response = await middleware.dispatch(
            mock_request, lambda req: asyncio.ensure_future(app.__call__(req.scope, req.receive, req.send))
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self, mock_request):
        """When downstream raises CancelledError, middleware should re-raise it."""
        app = MockASGIApp(raise_cancelled=True)
        middleware = CancellationPropagationMiddleware(app)

        async def call_next(req):
            return await app.__call__(req.scope, req.receive, req.send)

        with pytest.raises(asyncio.CancelledError):
            await middleware.dispatch(mock_request, call_next)

    @pytest.mark.asyncio
    async def test_downstream_tasks_cancelled_on_cancellation(self, mock_request):
        """Tracked downstream tasks should be cancelled when the request is cancelled."""
        middleware = CancellationPropagationMiddleware(MockASGIApp())

        async def delayed_task():
            try:
                await asyncio.sleep(10)
                return "done"
            except asyncio.CancelledError:
                return "cancelled"

        task = asyncio.create_task(delayed_task())
        mock_request.state._downstream_tasks.add(task)

        async def call_next(req):
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await middleware.dispatch(mock_request, call_next)

        # The task should have been cancelled
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_state_cleaned_up_in_finally(self, mock_request):
        """Request state should be cleaned up after dispatch, even on error."""
        middleware = CancellationPropagationMiddleware(MockASGIApp())

        async def call_next(req):
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await middleware.dispatch(mock_request, call_next)

        assert mock_request.state._downstream_tasks is None

    @pytest.mark.asyncio
    async def test_normal_no_downstream_tasks(self, mock_request):
        """Middleware should work correctly with no downstream tasks registered."""
        middleware = CancellationPropagationMiddleware(MockASGIApp(Response(status_code=200)))

        async def call_next(req):
            return Response(status_code=200)

        response = await middleware.dispatch(mock_request, call_next)
        assert response.status_code == 200
        assert mock_request.state._downstream_tasks is None


class TestAuthMiddleware:
    """Verify auth middleware behavior."""

    @pytest.mark.asyncio
    async def test_requires_bearer_token(self, mock_request):
        """Requests to /api/v2 without Bearer token should be rejected."""
        app = MockASGIApp()
        middleware = AuthMiddleware(app)

        async def call_next(req):
            return await app.__call__(req.scope, req.receive, req.send)

        response = await middleware.dispatch(mock_request, call_next)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_passes_with_bearer_token(self, mock_request):
        """Requests with valid Bearer token should pass through."""
        scope = dict(mock_request.scope)
        scope["headers"] = [(b"host", b"testserver"), (b"authorization", b"Bearer test-token")]
        authed_request = Request(scope)
        authed_request.state = State()
        app = MockASGIApp(Response(status_code=200))
        middleware = AuthMiddleware(app)

        async def call_next(req):
            return Response(status_code=200)

        response = await middleware.dispatch(authed_request, call_next)
        assert response.status_code == 200


class TestLoggingMiddleware:
    """Verify logging middleware doesn't swallow CancelledError."""

    @pytest.mark.asyncio
    async def test_cancellation_passthrough(self, mock_request):
        """CancelledError should be re-raised, not swallowed."""
        app = MockASGIApp(raise_cancelled=True)
        middleware = LoggingMiddleware(app)

        async def call_next(req):
            return await app.__call__(req.scope, req.receive, req.send)

        with pytest.raises(asyncio.CancelledError):
            await middleware.dispatch(mock_request, call_next)
