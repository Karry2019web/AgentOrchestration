"""Tests for the TimeoutMiddleware."""
import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.requests import Request
import asyncio

from src.api.middleware import TimeoutMiddleware


class TestTimeoutMiddleware:
    @pytest.fixture
    def app(self):
        app = Starlette()
        app.add_middleware(TimeoutMiddleware, default_timeout=0.05, stream_timeout=0.1)

        @app.route("/fast")
        async def fast(request):
            return Response("ok")

        @app.route("/slow")
        async def slow(request):
            await asyncio.sleep(0.2)
            return Response("slow")

        @app.route("/api/v2/events/stream")
        async def stream_endpoint(request):
            await asyncio.sleep(0.01)
            return Response("event data")

        return app

    def test_fast_request_succeeds(self, app):
        client = TestClient(app)
        response = client.get("/fast")
        assert response.status_code == 200

    def test_slow_request_times_out(self, app):
        client = TestClient(app)
        response = client.get("/slow")
        assert response.status_code == 408

    def test_streaming_endpoint_within_timeout(self, app):
        client = TestClient(app)
        response = client.get("/api/v2/events/stream")
        assert response.status_code == 200

    def test_non_streaming_default_timeout(self, app):
        client = TestClient(app)
        response = client.get("/slow")
        assert "timed out" in response.text.lower()
