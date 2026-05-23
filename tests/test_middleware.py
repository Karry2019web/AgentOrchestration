"""Tests for API middleware — JWT audience enforcement for service-to-service calls."""

import time
import jwt
import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.middleware import AuthMiddleware, _decode_token, JWT_AUDIENCE, JWT_SECRET

# Use a fixed secret for all test tokens
TEST_SECRET = "test-secret-key-12345"


def _make_token(payload: dict, secret: str = TEST_SECRET) -> str:
    """Create a signed JWT for testing."""
    return jwt.encode(payload, secret, algorithm="HS256")


class TestDecodeToken:
    """Unit tests for the _decode_token helper."""

    def test_valid_token(self):
        token = _make_token({
            "sub": "user:alice",
            "aud": JWT_AUDIENCE,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        })
        payload = _decode_token(f"Bearer {token}")
        assert payload is not None
        assert payload["sub"] == "user:alice"

    def test_expired_token(self):
        token = _make_token({
            "sub": "user:alice",
            "aud": JWT_AUDIENCE,
            "exp": int(time.time()) - 60,
            "iat": int(time.time()) - 120,
        })
        payload = _decode_token(f"Bearer {token}")
        assert payload is None

    def test_missing_bearer_prefix(self):
        payload = _decode_token("token-without-bearer")
        assert payload is None

    def test_empty_token(self):
        payload = _decode_token("Bearer ")
        assert payload is None

    def test_malformed_token(self):
        payload = _decode_token("Bearer not-a-valid.jwt.format")
        assert payload is None

    def test_anonymous_no_token(self):
        payload = _decode_token("")
        assert payload is None

    def test_wrong_audience(self):
        token = _make_token({
            "sub": "service:worker-1",
            "aud": "wrong-service",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        })
        payload = _decode_token(f"Bearer {token}")
        # _decode_token with a secret configured will reject wrong audience
        # Temporarily patch JWT_SECRET for this test
        import src.api.middleware as mw
        orig_secret = mw.JWT_SECRET
        mw.JWT_SECRET = TEST_SECRET
        try:
            payload = _decode_token(f"Bearer {token}")
            assert payload is None
        finally:
            mw.JWT_SECRET = orig_secret


class TestAuthMiddleware:
    """Integration-style tests for AuthMiddleware."""

    @pytest.fixture
    def middleware(self):
        app = _DummyApp()
        return AuthMiddleware(app), app

    def test_public_auth_token_endpoint(self):
        """The /api/v2/auth/token endpoint should be accessible without auth."""
        app = _DummyApp()
        mw = AuthMiddleware(app)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v2/auth/token",
            "headers": [],
        }
        request = Request(scope)
        response = _run_middleware(mw, request)
        assert response.status_code == 200

    def test_non_api_path_passes_through(self):
        """Paths outside /api/v2 should not be intercepted."""
        app = _DummyApp()
        mw = AuthMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [],
        }
        request = Request(scope)
        response = _run_middleware(mw, request)
        assert response.status_code == 200

    def test_protected_endpoint_requires_token(self):
        """Protected /api/v2 endpoints should reject requests without a token."""
        app = _DummyApp()
        mw = AuthMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents",
            "headers": [],
        }
        request = Request(scope)
        response = _run_middleware(mw, request)
        assert response.status_code == 401

    def test_valid_user_token_allowed(self):
        """A valid user token should pass through."""
        app = _DummyApp()
        mw = AuthMiddleware(app)
        token = _make_token({
            "sub": "user:alice",
            "aud": JWT_AUDIENCE,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        })
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
        request = Request(scope)
        import src.api.middleware as mw_mod
        orig_secret = mw_mod.JWT_SECRET
        mw_mod.JWT_SECRET = TEST_SECRET
        try:
            response = _run_middleware(mw, request)
            assert response.status_code == 200
        finally:
            mw_mod.JWT_SECRET = orig_secret

    def test_service_token_with_wrong_audience_blocked(self):
        """A service token with a mismatched audience should be rejected."""
        app = _DummyApp()
        mw = AuthMiddleware(app)
        token = _make_token({
            "sub": "service:worker-1",
            "aud": "wrong-service",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        })
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
        request = Request(scope)
        import src.api.middleware as mw_mod
        orig_secret = mw_mod.JWT_SECRET
        mw_mod.JWT_SECRET = TEST_SECRET
        try:
            response = _run_middleware(mw, request)
            assert response.status_code == 403
        finally:
            mw_mod.JWT_SECRET = orig_secret

    def test_service_token_with_correct_audience_allowed(self):
        """A service token with the correct audience should pass through."""
        app = _DummyApp()
        mw = AuthMiddleware(app)
        token = _make_token({
            "sub": "service:worker-1",
            "aud": JWT_AUDIENCE,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        })
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
        request = Request(scope)
        import src.api.middleware as mw_mod
        orig_secret = mw_mod.JWT_SECRET
        mw_mod.JWT_SECRET = TEST_SECRET
        try:
            response = _run_middleware(mw, request)
            assert response.status_code == 200
        finally:
            mw_mod.JWT_SECRET = orig_secret

    def test_stale_revoked_token_denied(self):
        """A token with a stale 'iat' (issued too long ago) should be denied."""
        app = _DummyApp()
        mw = AuthMiddleware(app)
        token = _make_token({
            "sub": "service:worker-1",
            "aud": JWT_AUDIENCE,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()) - 86400 * 8,  # 8 days old
        })
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
        request = Request(scope)
        import src.api.middleware as mw_mod
        orig_secret = mw_mod.JWT_SECRET
        orig_max_age = mw_mod.MAX_TOKEN_AGE
        mw_mod.JWT_SECRET = TEST_SECRET
        mw_mod.MAX_TOKEN_AGE = 86400 * 7  # 7 days max age
        # Re-bind the module-level constant for _decode_token to pick up
        try:
            from src.api.middleware import _decode_token as dt
            result = dt(f"Bearer {token}")
            assert result is None, "Token older than MAX_TOKEN_AGE should be rejected"
        finally:
            mw_mod.JWT_SECRET = orig_secret
            mw_mod.MAX_TOKEN_AGE = orig_max_age


class _DummyApp:
    """Minimal ASGI app that returns 200 OK."""

    async def __call__(self, scope, receive, send):
        response = Response(status_code=200)
        await response(scope, receive, send)


def _run_middleware(mw: BaseHTTPMiddleware, request: Request) -> Response:
    """Synchronously run a middleware's dispatch on a request."""
    import asyncio

    async def _run():
        call_next = _DummyApp()
        return await mw.dispatch(request, call_next)

    return asyncio.run(_run())
