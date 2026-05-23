"""Tests for AuthMiddleware trailing slash bypass prevention."""
import pytest


@pytest.mark.asyncio
async def test_auth_middleware_blocks_unauthenticated_request():
    """Test that unauthenticated requests to /api/v2 endpoints are blocked."""
    from src.api.server import create_app
    from httpx import AsyncClient, ASGITransport

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v2/agents")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_blocks_trailing_slash_bypass():
    """Test that trailing slash doesn't bypass auth."""
    from src.api.server import create_app
    from httpx import AsyncClient, ASGITransport

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v2/agents/")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_blocks_double_slash_bypass():
    """Test that double slashes don't bypass auth."""
    from src.api.server import create_app
    from httpx import AsyncClient, ASGITransport

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v2//agents")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_allows_token_endpoint():
    """Test that token endpoint is accessible without auth."""
    from src.api.server import create_app
    from httpx import AsyncClient, ASGITransport

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v2/auth/token")
        assert response.status_code != 401


@pytest.mark.asyncio
async def test_auth_middleware_authenticated_request():
    """Test that authenticated requests succeed."""
    from src.api.server import create_app
    from httpx import AsyncClient, ASGITransport

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer valid-token"}
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_endpoint_no_auth_required():
    """Test that /health endpoint doesn't require auth."""
    from src.api.server import create_app
    from httpx import AsyncClient, ASGITransport

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
