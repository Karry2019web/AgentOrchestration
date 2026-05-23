"""Tests for API middleware — request context isolation and correlation IDs."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import (
    RequestContextMiddleware,
    AuthMiddleware,
    RateLimitMiddleware,
    LoggingMiddleware,
    correlation_id_var,
    tenant_id_var,
    request_id_var,
    get_correlation_id,
    get_tenant_id,
    get_request_id,
)


class TestRequestContextMiddleware:
    """Tests for RequestContextMiddleware — correlation ID/tenant isolation."""

    def setup_method(self):
        self.middleware = RequestContextMiddleware(MagicMock())
        # Reset context vars before each test
        correlation_id_var.set("")
        tenant_id_var.set("")
        request_id_var.set("")

    @pytest.mark.asyncio
    async def test_sets_correlation_id_from_header(self):
        """Normal request: correlation ID from incoming header is propagated."""
        request = MagicMock(spec=Request)
        request.headers = {
            "X-Correlation-ID": "corr-123",
            "X-Tenant-ID": "tenant-acme",
        }
        request.url.path = "/api/v2/agents"

        response = Response(status_code=200, content="ok")

        async def call_next(req):
            assert get_correlation_id() == "corr-123"
            assert get_tenant_id() == "tenant-acme"
            assert get_request_id() != ""
            return response

        result = await self.middleware.dispatch(request, call_next)
        assert result.headers["X-Correlation-ID"] == "corr-123"
        assert result.headers["X-Request-ID"] is not None
        assert result.headers["X-Tenant-ID"] == "tenant-acme"

        # After dispatch, context vars must be reset
        assert correlation_id_var.get() == ""
        assert tenant_id_var.get() == ""
        assert request_id_var.get() == ""

    @pytest.mark.asyncio
    async def test_generates_correlation_id_when_missing(self):
        """Normal request without header: middleware generates a new correlation ID."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/api/v2/agents"

        response = Response(status_code=200, content="ok")

        async def call_next(req):
            cid = get_correlation_id()
            assert cid != ""
            assert cid != "corr-123"  # should be unique
            return response

        result = await self.middleware.dispatch(request, call_next)
        assert result.headers["X-Correlation-ID"] is not None
        assert result.headers["X-Request-ID"] is not None

        # Context reset after dispatch
        assert correlation_id_var.get() == ""
        assert tenant_id_var.get() == ""

    @pytest.mark.asyncio
    async def test_default_tenant_is_anonymous(self):
        """Request without tenant header: tenant defaults to 'anonymous'."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/api/v2/agents"

        async def call_next(req):
            assert get_tenant_id() == "anonymous"
            return Response(status_code=200, content="ok")

        await self.middleware.dispatch(request, call_next)
        assert tenant_id_var.get() == ""

    @pytest.mark.asyncio
    async def test_exception_path_does_not_leak_context(self):
        """Error path: context is cleared even when the handler raises."""
        request = MagicMock(spec=Request)
        request.headers = {
            "X-Correlation-ID": "corr-error",
            "X-Tenant-ID": "tenant-error",
        }
        request.url.path = "/api/v2/agents"

        async def call_next(req):
            raise ValueError("Something went wrong")

        result = await self.middleware.dispatch(request, call_next)
        # Should return 500 with tracing headers
        assert result.status_code == 500
        assert result.headers["X-Correlation-ID"] == "corr-error"
        assert result.headers["X-Request-ID"] is not None

        # Context fully reset despite error
        assert correlation_id_var.get() == ""
        assert tenant_id_var.get() == ""
        assert request_id_var.get() == ""

    @pytest.mark.asyncio
    async def test_no_leak_between_sequential_requests(self):
        """Sequential requests: second request's context doesn't mix with first."""
        request_a = MagicMock(spec=Request)
        request_a.headers = {"X-Correlation-ID": "req-a", "X-Tenant-ID": "tenant-a"}
        request_a.url.path = "/api/v2/agents"

        request_b = MagicMock(spec=Request)
        request_b.headers = {"X-Correlation-ID": "req-b", "X-Tenant-ID": "tenant-b"}
        request_b.url.path = "/api/v2/agents"

        results = []

        async def handler_a(req):
            results.append(("a", get_correlation_id(), get_tenant_id()))
            return Response(status_code=200, content="ok")

        async def handler_b(req):
            results.append(("b", get_correlation_id(), get_tenant_id()))
            return Response(status_code=200, content="ok")

        await self.middleware.dispatch(request_a, handler_a)
        await self.middleware.dispatch(request_b, handler_b)

        # Each handler saw only its own context
        assert results[0] == ("a", "req-a", "tenant-a")
        assert results[1] == ("b", "req-b", "tenant-b")

        # After both: context vars are reset
        assert correlation_id_var.get() == ""
        assert tenant_id_var.get() == ""
        assert request_id_var.get() == ""


class TestAuthMiddleware:
    def setup_method(self):
        self.middleware = AuthMiddleware(MagicMock())

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self):
        request = MagicMock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.headers = {}

        async def call_next(req):
            return Response(status_code=200)

        response = await self.middleware.dispatch(request, call_next)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_auth_passes(self):
        request = MagicMock(spec=Request)
        request.url.path = "/api/v2/agents"
        request.headers = {"Authorization": "Bearer valid-token"}

        async def call_next(req):
            return Response(status_code=200)

        response = await self.middleware.dispatch(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_endpoint_skips_validation(self):
        request = MagicMock(spec=Request)
        request.url.path = "/api/v2/auth/token"
        request.headers = {}

        async def call_next(req):
            return Response(status_code=200)

        response = await self.middleware.dispatch(request, call_next)
        assert response.status_code == 200
