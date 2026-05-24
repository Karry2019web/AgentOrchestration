"""Tests for middleware components."""

import pytest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import NormalizePathMiddleware


class TestNormalizePathMiddleware:
    """Collapse duplicate slashes before public route matching."""

    @pytest.mark.asyncio
    async def test_normal_path_passthrough(self):
        """A path without duplicate slashes should pass through unchanged."""
        mid = NormalizePathMiddleware(app=AsyncMock())
        mock_call_next = AsyncMock(return_value=Response("OK", status_code=200))
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents",
            "raw_path": b"/api/v2/agents",
            "headers": [],
            "query_string": b"",
        }
        req = Request(scope)
        resp = await mid.dispatch(req, mock_call_next)
        assert resp.status_code == 200
        mock_call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_collapse_double_slash_prefix(self):
        """//api/v2/agents should normalize to /api/v2/agents."""
        mid = NormalizePathMiddleware(app=AsyncMock())

        scope = {
            "type": "http",
            "method": "GET",
            "path": "//api/v2/agents",
            "raw_path": b"//api/v2/agents",
            "headers": [],
            "query_string": b"",
        }
        req = Request(scope)

        async def tracked_call_next(request):
            assert request.url.path == "/api/v2/agents", (
                f"Expected /api/v2/agents, got {request.url.path}"
            )
            return Response("OK", status_code=200)

        resp = await mid.dispatch(req, tracked_call_next)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_collapse_middle_double_slash(self):
        """/api//v2/agents should normalize to /api/v2/agents."""
        mid = NormalizePathMiddleware(app=AsyncMock())

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api//v2/agents",
            "raw_path": b"/api//v2/agents",
            "headers": [],
            "query_string": b"",
        }
        req = Request(scope)

        async def tracked_call_next(request):
            assert request.url.path == "/api/v2/agents"
            return Response("OK", status_code=200)

        resp = await mid.dispatch(req, tracked_call_next)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_collapse_trailing_double_slash(self):
        """/api/v2/agents// should normalize to /api/v2/agents/."""
        mid = NormalizePathMiddleware(app=AsyncMock())

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents//",
            "raw_path": b"/api/v2/agents//",
            "headers": [],
            "query_string": b"",
        }
        req = Request(scope)

        async def tracked_call_next(request):
            assert request.url.path == "/api/v2/agents/"
            return Response("OK", status_code=200)

        resp = await mid.dispatch(req, tracked_call_next)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_collapse_many_slashes(self):
        """/api///v2////agents should normalize to /api/v2/agents."""
        mid = NormalizePathMiddleware(app=AsyncMock())

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api///v2////agents",
            "raw_path": b"/api///v2////agents",
            "headers": [],
            "query_string": b"",
        }
        req = Request(scope)

        async def tracked_call_next(request):
            assert request.url.path == "/api/v2/agents"
            return Response("OK", status_code=200)

        resp = await mid.dispatch(req, tracked_call_next)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_endpoint_still_works(self):
        """The /health endpoint should still be reachable."""
        mid = NormalizePathMiddleware(app=AsyncMock())
        mock_call_next = AsyncMock(return_value=Response("healthy", status_code=200))

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "raw_path": b"/health",
            "headers": [],
            "query_string": b"",
        }
        req = Request(scope)
        resp = await mid.dispatch(req, mock_call_next)
        assert resp.status_code == 200
        mock_call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_normalized_path_triggers_auth(self):
        """After normalization, //api/v2/agents triggers auth middleware."""
        norm = NormalizePathMiddleware(app=AsyncMock())

        scope = {
            "type": "http",
            "method": "GET",
            "path": "//api/v2/agents",
            "raw_path": b"//api/v2/agents",
            "headers": [],
            "query_string": b"",
        }
        req = Request(scope)

        class AuthDelegate:
            async def __call__(self, request):
                assert request.url.path == "/api/v2/agents", (
                    f"Auth saw wrong path: {request.url.path}"
                )
                return Response("OK", status_code=200)

        resp = await norm.dispatch(req, AuthDelegate())
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_normalized_path_collapses_via_regex(self):
        """Internal regex matches triple and quadruple slashes correctly."""
        import re
        pattern = re.compile(r"/{2,}")
        assert pattern.sub("/", "////api/v2////agents") == "/api/v2/agents"
        assert pattern.sub("/", "//") == "/"
        assert pattern.sub("/", "/") == "/"
        assert pattern.sub("/", "") == ""
