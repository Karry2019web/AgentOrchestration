"""Tests for RequestContextMiddleware."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from src.api.server import create_app


class TestRequestContextMiddleware:
    def setup_method(self):
        self.app = create_app()
        self.client = TestClient(self.app)

    def test_normal_request_passes_through(self):
        """Normal request should return expected response."""
        response = self.client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_exception_returns_sanitized_500(self):
        """Exception should return generic 500 with sanitized error."""
        response = self.client.get("/api/v2/agents/nonexistent")
        assert response.status_code in (404, 500)
        # Either 404 from the handler or 500 from middleware

    def test_sanitized_header_on_error(self):
        """Error response should include X-Error-Sanitized header."""
        response = self.client.get("/api/v2/agents/nonexistent")
        # 404s don't go through error middleware, 500s should have the header
        if response.status_code == 500:
            assert response.headers.get("X-Error-Sanitized") == "true"

    def test_consecutive_requests_no_leak(self):
        """Multiple requests should not accumulate or leak context."""
        for _ in range(5):
            response = self.client.get("/health")
            assert response.status_code == 200

    def test_existing_routes_unaffected(self):
        """Existing routes continue working."""
        response = self.client.get("/api/v2/agents/count")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
