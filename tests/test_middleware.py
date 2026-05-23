"""Tests for request context middleware — correlation ID tenant isolation."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.middleware import (
    RequestContextMiddleware,
    get_request_id,
    get_tenant_id,
    get_user_id,
)


@pytest.fixture
def mock_request():
    """Create a mock request for testing."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v2/agents",
        "headers": [],
    }
    request = MagicMock(spec=Request)
    request.url.path = "/api/v2/agents"
    request.method = "GET"
    request.headers = {}
    request.state = MagicMock()
    request.scope = scope
    return request


@pytest.fixture
def middleware():
    return RequestContextMiddleware(MagicMock())


@pytest.mark.asyncio
async def test_normal_request_generates_correlation_id(middleware, mock_request):
    """Normal requests should get a unique correlation ID."""
    call_next = AsyncMock(return_value=Response(status_code=200))

    response = await middleware.dispatch(mock_request, call_next)

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"] != ""
    assert mock_request.state.request_id is not None
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_with_external_correlation_id(middleware, mock_request):
    """External correlation IDs in headers should be preserved."""
    expected_id = "ext-correlation-abc-123"
    mock_request.headers = {"X-Correlation-ID": expected_id}

    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await middleware.dispatch(mock_request, call_next)

    assert response.headers["X-Request-ID"] == expected_id
    assert mock_request.state.request_id == expected_id


@pytest.mark.asyncio
async def test_tenant_id_isolation(middleware, mock_request):
    """Different tenants should have correct tenant IDs."""
    mock_request.headers = {"X-Tenant-ID": "tenant-alpha"}

    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await middleware.dispatch(mock_request, call_next)

    assert response.headers["X-Tenant-ID"] == "tenant-alpha"
    assert mock_request.state.tenant_id == "tenant-alpha"


@pytest.mark.asyncio
async def test_default_tenant_when_not_provided(middleware, mock_request):
    """Requests without tenant header should use 'default'."""
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await middleware.dispatch(mock_request, call_next)

    assert response.headers["X-Tenant-ID"] == "default"


@pytest.mark.asyncio
async def test_context_vars_accessible_via_getters(middleware, mock_request):
    """Context vars should be accessible via module-level getters within request."""
    mock_request.headers = {
        "X-Correlation-ID": "ctx-test-456",
        "X-Tenant-ID": "ctx-tenant-789",
        "X-User-ID": "ctx-user-012",
    }

    async def check_context(request):
        assert get_request_id() == "ctx-test-456"
        assert get_tenant_id() == "ctx-tenant-789"
        assert get_user_id() == "ctx-user-012"
        return Response(status_code=200)

    call_next = check_context
    response = await middleware.dispatch(mock_request, call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_context_vars_cleared_after_normal_request(middleware, mock_request):
    """Context vars should be reset after request completes (no leak)."""
    mock_request.headers = {
        "X-Correlation-ID": "leak-test-1",
        "X-Tenant-ID": "leak-tenant-1",
    }

    call_next = AsyncMock(return_value=Response(status_code=200))
    await middleware.dispatch(mock_request, call_next)

    # Outside the request, context vars should be empty
    assert get_request_id() == ""
    assert get_tenant_id() == ""
    assert get_user_id() == ""


@pytest.mark.asyncio
async def test_context_vars_cleared_on_exception(middleware, mock_request):
    """Context vars must be cleared when middleware encounters an exception."""
    mock_request.headers = {
        "X-Correlation-ID": "err-test-1",
        "X-Tenant-ID": "err-tenant-1",
    }

    async def failing_call_next(request):
        raise RuntimeError("Simulated failure")

    with pytest.raises(RuntimeError):
        await middleware.dispatch(mock_request, failing_call_next)

    # Even after exception, context vars should be clean
    assert get_request_id() == ""
    assert get_tenant_id() == ""
    assert get_user_id() == ""


@pytest.mark.asyncio
async def test_multiple_concurrent_requests_independent(middleware, mock_request):
    """Concurrent simulated requests should not cross-contaminate context vars."""
    results = {}

    async def make_request(corr_id, tenant_id, user_id):
        req = MagicMock(spec=Request)
        req.url.path = "/api/v2/agents"
        req.method = "GET"
        req.headers = {
            "X-Correlation-ID": corr_id,
            "X-Tenant-ID": tenant_id,
            "X-User-ID": user_id,
        }
        req.state = MagicMock()
        req.scope = {"type": "http", "method": "GET", "path": "/api/v2/agents", "headers": []}

        async def check_and_return(request):
            # Capture the context vars inside the request
            return Response(
                status_code=200,
                headers={
                    "X-Request-ID": get_request_id(),
                    "X-Tenant-ID": get_tenant_id(),
                    "X-User-ID": get_user_id(),
                },
            )

        return await middleware.dispatch(req, check_and_return)

    import asyncio
    tasks = [
        make_request("corr-a", "tenant-a", "user-a"),
        make_request("corr-b", "tenant-b", "user-b"),
        make_request("corr-c", "tenant-c", "user-c"),
    ]
    responses = await asyncio.gather(*tasks)

    expected = [
        ("corr-a", "tenant-a", "user-a"),
        ("corr-b", "tenant-b", "user-b"),
        ("corr-c", "tenant-c", "user-c"),
    ]
    for resp, (exp_corr, exp_ten, exp_user) in zip(responses, expected):
        assert resp.headers["X-Request-ID"] == exp_corr
        assert resp.headers["X-Tenant-ID"] == exp_ten
        assert resp.headers["X-User-ID"] == exp_user

    # After all requests, context should be clean
    assert get_request_id() == ""
    assert get_tenant_id() == ""
    assert get_user_id() == ""


@pytest.mark.asyncio
async def test_response_headers_on_rejected_request(middleware, mock_request):
    """Even rejected requests should get correlation ID headers."""
    async def rejecting_call_next(request):
        return Response(status_code=403, content="Forbidden")

    response = await middleware.dispatch(mock_request, rejecting_call_next)
    assert response.status_code == 403
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"] != ""
