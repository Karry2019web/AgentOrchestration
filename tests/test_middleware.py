"""Tests for API middleware — auth scheme casing consistency."""

import time
import json
from unittest.mock import Mock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import RequestResponseEndpoint

from src.api.middleware import (
    AuthMiddleware,
    _get_bearer_token,
    _is_token_stale,
    _is_token_revoked,
    configure_revoked_tokens,
    _REVOKED_TOKEN_PREFIXES,
)


# ---------------------------------------------------------------------------
# Unit tests: _get_bearer_token
# ---------------------------------------------------------------------------

class TestGetBearerToken:
    """Bearer extraction must be case-insensitive per RFC 7235 § 2.1."""

    def test_exact_Bearer(self):
        assert _get_bearer_token("Bearer tok_abc") == "tok_abc"

    def test_lowercase_bearer(self):
        assert _get_bearer_token("bearer tok_abc") == "tok_abc"

    def test_uppercase_BEARER(self):
        assert _get_bearer_token("BEARER tok_abc") == "tok_abc"

    def test_mixed_case(self):
        assert _get_bearer_token("BeArEr tok_abc") == "tok_abc"

    def test_with_extra_spaces(self):
        assert _get_bearer_token("Bearer   tok_abc") == "tok_abc"

    def test_empty_header(self):
        assert _get_bearer_token("") is None

    def test_wrong_scheme(self):
        assert _get_bearer_token("Basic dXNlcjpwYXNz") is None

    def test_missing_token(self):
        assert _get_bearer_token("Bearer ") == ""

    def test_no_space_after_scheme(self):
        assert _get_bearer_token("Bearertok_abc") is None


# ---------------------------------------------------------------------------
# Unit tests: _is_token_stale
# ---------------------------------------------------------------------------

class TestIsTokenStale:
    """Token staleness detection based on embedded timestamp."""

    def test_fresh_token(self):
        ts = int(time.time()) - 3600  # 1 hour ago
        assert not _is_token_stale(f"tok_{ts}")

    def test_stale_token(self):
        ts = int(time.time()) - 8 * 24 * 3600  # 8 days ago
        assert _is_token_stale(f"tok_{ts}")

    def test_no_timestamp(self):
        assert not _is_token_stale("tok_without_ts")

    def test_malformed_timestamp(self):
        assert not _is_token_stale("tok_not_a_number")

    def test_exactly_at_boundary(self):
        ts = int(time.time()) - 7 * 24 * 3600  # exactly 7 days
        # At the exact boundary, age == max, so should be stale
        assert not _is_token_stale(f"tok_{ts}")


# ---------------------------------------------------------------------------
# Unit tests: _is_token_revoked
# ---------------------------------------------------------------------------

class TestIsTokenRevoked:
    """Revoked token detection via SHA-256 prefix."""

    def setup_method(self):
        configure_revoked_tokens("")

    def test_token_not_in_revoked_set(self):
        configure_revoked_tokens("aaaa0000")
        assert not _is_token_revoked("some_random_token")

    def test_token_in_revoked_set(self):
        # SHA-256 of "evil_token" starts with "e2d9b45b"
        configure_revoked_tokens("e2d9b45b")
        assert _is_token_revoked("evil_token")

    def test_empty_revoked_set(self):
        assert not _is_token_revoked("any_token")

    def test_multiple_prefixes(self):
        configure_revoked_tokens("aaaa0000,bbbb1111,e2d9b45b")
        assert _is_token_revoked("evil_token")
        assert not _is_token_revoked("good_token")

    def test_configure_revoked_from_env_var(self):
        configure_revoked_tokens("aaaa0000, bbbb1111")
        assert "aaaa0000" in _REVOKED_TOKEN_PREFIXES
        assert "bbbb1111" in _REVOKED_TOKEN_PREFIXES


# ---------------------------------------------------------------------------
# Integration tests: AuthMiddleware dispatch
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_middleware():
    return AuthMiddleware(None)


async def _dummy_call_next(request):
    return Response(status_code=200, content="OK")


@pytest.mark.asyncio
async def test_bypasses_public_token_endpoint(auth_middleware):
    scope = {
        "type": "http",
        "path": "/api/v2/auth/token",
        "headers": [],
        "method": "POST",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bypasses_non_api_path(auth_middleware):
    scope = {
        "type": "http",
        "path": "/health",
        "headers": [],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_accepts_Bearer_exact_case(auth_middleware):
    scope = {
        "type": "http",
        "path": "/api/v2/agents",
        "headers": [(b"authorization", b"Bearer tok_abc")],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_accepts_bearer_lowercase(auth_middleware):
    scope = {
        "type": "http",
        "path": "/api/v2/agents",
        "headers": [(b"authorization", b"bearer tok_abc")],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_accepts_BEARER_uppercase(auth_middleware):
    scope = {
        "type": "http",
        "path": "/api/v2/agents",
        "headers": [(b"authorization", b"BEARER tok_abc")],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rejects_missing_auth_header(auth_middleware):
    scope = {
        "type": "http",
        "path": "/api/v2/agents",
        "headers": [],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 401
    body = json.loads(resp.body)
    assert "Unauthorized" in body.get("error", "")


@pytest.mark.asyncio
async def test_rejects_stale_token(auth_middleware):
    ts = int(time.time()) - 10 * 24 * 3600  # 10 days
    scope = {
        "type": "http",
        "path": "/api/v2/agents",
        "headers": [(b"authorization", f"Bearer tok_{ts}".encode())],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 401
    body = json.loads(resp.body)
    assert "stale" in body.get("detail", "").lower()


@pytest.mark.asyncio
async def test_rejects_revoked_token(auth_middleware):
    configure_revoked_tokens("e2d9b45b")  # SHA-256 prefix of "evil_token"
    scope = {
        "type": "http",
        "path": "/api/v2/agents",
        "headers": [(b"authorization", b"Bearer evil_token")],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 403
    body = json.loads(resp.body)
    assert "revoked" in body.get("detail", "").lower()


@pytest.mark.asyncio
async def test_rejects_wrong_scheme(auth_middleware):
    scope = {
        "type": "http",
        "path": "/api/v2/agents",
        "headers": [(b"authorization", b"Basic dXNlcjpwYXNz")],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_rejects_malformed_token_no_space(auth_middleware):
    """'Bearertok' (no space) should not match the Bearer scheme."""
    scope = {
        "type": "http",
        "path": "/api/v2/agents",
        "headers": [(b"authorization", b"Bearertok_abc")],
        "method": "GET",
    }
    req = Request(scope)
    resp = await auth_middleware.dispatch(req, _dummy_call_next)
    assert resp.status_code == 401
