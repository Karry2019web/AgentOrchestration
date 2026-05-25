"""Tests for API middleware — OpenAPI schema auth protection."""

import pytest
from fastapi.testclient import TestClient
from src.api import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestOpenAPIAuthProtection:
    """Verify that OpenAPI schema and docs endpoints require authentication."""

    def test_openapi_schema_requires_auth(self, client):
        """GET /openapi.json without auth should return 401."""
        response = client.get("/openapi.json")
        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text[:100]}"
        )

    def test_openapi_schema_allows_valid_token(self, client):
        """GET /openapi.json with a valid Bearer token should succeed."""
        response = client.get(
            "/openapi.json",
            headers={"Authorization": "Bearer valid-test-token"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:100]}"
        )

    def test_docs_endpoint_requires_auth(self, client):
        """GET /api/docs without auth should return 401."""
        response = client.get("/api/docs")
        assert response.status_code == 401

    def test_redoc_endpoint_requires_auth(self, client):
        """GET /api/redoc without auth should return 401."""
        response = client.get("/api/redoc")
        assert response.status_code == 401

    def test_health_endpoint_public(self, client):
        """GET /health should work without auth."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_openapi_schema_rejected_with_stale_token(self, client):
        """GET /openapi.json with stale/malformed token should be rejected."""
        for bad_header in [
            {"Authorization": "Bearer stale"},
            {"Authorization": "Bearer"},
            {"Authorization": ""},
            {},
        ]:
            response = client.get("/openapi.json", headers=bad_header)
            assert response.status_code == 401, (
                f"Expected 401 for headers {bad_header}, got {response.status_code}"
            )
