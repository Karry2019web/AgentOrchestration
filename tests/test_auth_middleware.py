"""Tests for auth middleware trailing slash bypass protection."""

from fastapi.testclient import TestClient
from src.api.server import create_app


def test_trailing_slash_redirect_blocked_before_redirect():
    """Request to /api/v2/agents/ (trailing slash) must be blocked before redirect."""
    client = TestClient(create_app(), follow_redirects=False)
    response = client.get("/api/v2/agents/")
    assert response.status_code == 401
    assert response.text == "Unauthorized"


def test_canonical_path_noslash():
    """Request to /api/v2/agents (no trailing slash) must also require auth."""
    client = TestClient(create_app(), follow_redirects=False)
    response = client.get("/api/v2/agents")
    assert response.status_code == 401


def test_protected_route_with_valid_token():
    """Request with valid bearer token passes auth regardless of trailing slash."""
    client = TestClient(create_app(), follow_redirects=False)
    response = client.get(
        "/api/v2/agents/",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code != 401


def test_health_check_public():
    """Health endpoint must remain public outside /api/v2."""
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200


def test_public_token_endpoint():
    """Token endpoint must remain accessible without auth."""
    client = TestClient(create_app(), follow_redirects=False)
    for p in ["/api/v2/auth/token", "/api/v2/auth/token/"]:
        response = client.get(p)
        assert response.status_code != 401
