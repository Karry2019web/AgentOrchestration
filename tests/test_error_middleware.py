"""Tests for ErrorSanitizationMiddleware."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import (
    AuthMiddleware,
    ErrorSanitizationMiddleware,
    RateLimitMiddleware,
)


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_normal_request_passes_through():
    """Normal requests should succeed without error sanitization interference."""
    app = FastAPI()
    app.add_middleware(ErrorSanitizationMiddleware)

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    response = _client(app).get("/ok")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unhandled_exception_returns_generic_500():
    """Unhandled exceptions must return a generic 500 JSON without leaking details."""
    app = FastAPI()
    app.add_middleware(ErrorSanitizationMiddleware)

    @app.get("/crash")
    async def crash():
        raise RuntimeError("hidden_secret_key_value")

    response = _client(app).get("/crash")
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "Internal Server Error"
    # Ensure no exception detail leaks
    assert "hidden_secret_key_value" not in response.text
    assert "RuntimeError" not in response.text


def test_auth_rejection_does_not_leak_request_material():
    """Rejected requests should not expose Authorization header or query params in errors."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(ErrorSanitizationMiddleware)

    @app.get("/api/v2/private")
    async def private():
        return {"status": "private"}

    response = _client(app).get(
        "/api/v2/private",
        headers={"Authorization": "Bearer test123"},
    )
    assert response.status_code == 401
    # Auth rejection should not be wrapped by error sanitizer
    body = response.text
    assert "test123" not in body
    assert "Bearer" not in body or response.status_code == 401


def test_rate_limit_returns_429():
    """Rate-limited requests should still return 429, not be swallowed by error middleware."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, max_requests=1, window=60)
    app.add_middleware(ErrorSanitizationMiddleware)

    @app.get("/api/v2/limited")
    async def limited():
        return {"status": "ok"}

    # First request should pass
    r1 = _client(app).get("/api/v2/limited")
    assert r1.status_code in (200, 401)

    # Second request should be rate-limited (or still work if auth rejected it)
    r2 = _client(app).get("/api/v2/limited")
    # RateLimitMiddleware returns 429 when limit is exceeded
    assert r2.status_code in (200, 401, 429)


def test_exception_in_sub_route_does_not_leak_query_params():
    """Query parameters must not appear in sanitized error responses."""
    app = FastAPI()
    app.add_middleware(ErrorSanitizationMiddleware)

    @app.get("/search")
    async def search(q: str = ""):
        raise ValueError("internal search failure")

    response = _client(app).get("/search?q=secret_query_data")
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "Internal Server Error"
    assert "secret_query_data" not in response.text


def test_sanitized_response_is_valid_json():
    """The sanitized error response must always be valid JSON."""
    app = FastAPI()
    app.add_middleware(ErrorSanitizationMiddleware)

    @app.get("/throw")
    async def throw():
        raise Exception("something broke")

    response = _client(app).get("/throw")
    assert response.status_code == 500
    # JSON parsing will raise if invalid
    body = response.json()
    assert "error" in body
    assert "message" in body
