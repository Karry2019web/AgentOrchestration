"""Tests for worker auth token validation — nbf, exp, scope, workspace, anonymous."""

import base64
import json
import pytest

from src.common.auth import validate_worker_token, TokenValidationError, decode_jwt_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(payload: dict) -> str:
    """Build a minimal JWT-like token with *payload* as the body."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{body}.{sig}"


# ---------------------------------------------------------------------------
# Token structure
# ---------------------------------------------------------------------------

class TestTokenStructure:
    def test_empty_token_rejected(self):
        claims, err = validate_worker_token("")
        assert err == "empty token"
        assert claims == {}

    def test_whitespace_token_rejected(self):
        claims, err = validate_worker_token("   ")
        assert err == "empty token"

    def test_malformed_token_rejected(self):
        claims, err = validate_worker_token("not-a-jwt")
        assert err is not None
        assert "malformed" in err

    def test_two_part_token_rejected(self):
        claims, err = validate_worker_token("abc.def")
        assert err is not None

    def test_four_part_token_rejected(self):
        claims, err = validate_worker_token("a.b.c.d")
        assert err is not None

    def test_invalid_base64_rejected(self):
        claims, err = validate_worker_token("abc.!!!@#$.def")
        assert err is not None


# ---------------------------------------------------------------------------
# decode_jwt_payload unit tests
# ---------------------------------------------------------------------------

class TestDecodeJwtPayload:
    def test_decode_valid_payload(self):
        payload = {"sub": "worker-1", "nbf": 1000}
        token = _make_token(payload)
        result = decode_jwt_payload(token)
        assert result["sub"] == "worker-1"
        assert result["nbf"] == 1000

    def test_decode_raises_on_bad_padding(self):
        token = "eyJhbGciOiJIUzI1NiJ9.dGhpc2lzbm90dmFsaWRqc29u.sig"
        with pytest.raises(TokenValidationError):
            decode_jwt_payload(token)


# ---------------------------------------------------------------------------
# Not-before (nbf)
# ---------------------------------------------------------------------------

class TestNotBefore:
    def test_valid_nbf_passes(self):
        token = _make_token({"sub": "user1", "nbf": 1000, "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err is None
        assert claims["sub"] == "user1"

    def test_nbf_in_future_rejected(self):
        """Token with nbf=3000 used at now=1500 must be denied."""
        token = _make_token({"sub": "user1", "nbf": 3000, "exp": 4000})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "token not yet valid"
        assert claims == {}

    def test_nbf_exactly_now_passes(self):
        """When now == nbf the token should be accepted (boundary)."""
        token = _make_token({"sub": "user1", "nbf": 1000, "exp": 2000})
        claims, err = validate_worker_token(token, now=1000)
        assert err is None

    def test_nbf_just_before_now_passes(self):
        token = _make_token({"sub": "user1", "nbf": 1499, "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err is None

    def test_malformed_nbf_rejected(self):
        token = _make_token({"sub": "user1", "nbf": "not-a-number"})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "malformed nbf claim"

    def test_nbf_null_rejected(self):
        token = _make_token({"sub": "user1", "nbf": None})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "malformed nbf claim"


# ---------------------------------------------------------------------------
# Expiration (exp)
# ---------------------------------------------------------------------------

class TestExpiration:
    def test_expired_token_rejected(self):
        token = _make_token({"sub": "user1", "exp": 1000})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "token expired"

    def test_not_expired_passes(self):
        token = _make_token({"sub": "user1", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err is None

    def test_exactly_expired_rejected(self):
        """When now == exp the token is expired (boundary)."""
        token = _make_token({"sub": "user1", "exp": 1000})
        claims, err = validate_worker_token(token, now=1000)
        assert err == "token expired"

    def test_malformed_exp_rejected(self):
        token = _make_token({"sub": "user1", "exp": "bogus"})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "malformed exp claim"

    def test_missing_exp_with_nbf(self):
        """No exp claim: token passes (exp is optional for validation)."""
        token = _make_token({"sub": "user1", "nbf": 1000})
        claims, err = validate_worker_token(token, now=1500)
        assert err is None


# ---------------------------------------------------------------------------
# Anonymous / missing sub
# ---------------------------------------------------------------------------

class TestAnonymous:
    def test_anonymous_sub_rejected(self):
        token = _make_token({"sub": "anonymous", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "anonymous principal denied"

    def test_guest_sub_rejected(self):
        token = _make_token({"sub": "guest", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "anonymous principal denied"

    def test_empty_sub_rejected(self):
        token = _make_token({"sub": "", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "anonymous principal denied"

    def test_missing_sub_rejected(self):
        token = _make_token({"exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "anonymous principal denied"

    def test_non_string_sub_rejected(self):
        token = _make_token({"sub": 12345, "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "malformed sub claim"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

class TestScope:
    def test_valid_scope_passes(self):
        token = _make_token({"sub": "user1", "scopes": ["read", "worker"], "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, required_scope="worker")
        assert err is None

    def test_missing_scope_rejected(self):
        token = _make_token({"sub": "user1", "scopes": ["read"], "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, required_scope="worker")
        assert err == "insufficient scope"

    def test_no_scopes_claim_rejected(self):
        token = _make_token({"sub": "user1", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, required_scope="worker")
        assert err == "insufficient scope"

    def test_scope_string_comma_separated(self):
        token = _make_token({"sub": "user1", "scopes": "read, worker", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, required_scope="worker")
        assert err is None

    def test_space_separated_scope_claim(self):
        token = _make_token({"sub": "user1", "scope": "read worker", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, required_scope="worker")
        assert err is None

    def test_no_required_scope_skips_check(self):
        token = _make_token({"sub": "user1", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err is None


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------

class TestWorkspace:
    def test_matching_workspace_passes(self):
        token = _make_token({"sub": "user1", "workspace": "ws-abc", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, workspace="ws-abc")
        assert err is None

    def test_matching_workspace_id_passes(self):
        token = _make_token({"sub": "user1", "workspace_id": "ws-abc", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, workspace="ws-abc")
        assert err is None

    def test_mismatched_workspace_rejected(self):
        token = _make_token({"sub": "user1", "workspace": "ws-abc", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, workspace="ws-xyz")
        assert err == "workspace mismatch"

    def test_missing_workspace_rejected(self):
        token = _make_token({"sub": "user1", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500, workspace="ws-abc")
        assert err == "workspace mismatch"

    def test_no_workspace_check_skipped(self):
        token = _make_token({"sub": "user1", "exp": 2000})
        claims, err = validate_worker_token(token, now=1500)
        assert err is None


# ---------------------------------------------------------------------------
# Combined — stale + revoked + insufficient
# ---------------------------------------------------------------------------

class TestCombinedChecks:
    def test_stale_and_wrong_scope(self):
        """Even with wrong scope, nbf check runs first and wins."""
        token = _make_token({"sub": "user1", "nbf": 3000, "scopes": [], "exp": 4000})
        claims, err = validate_worker_token(token, now=1500, required_scope="admin")
        assert err == "token not yet valid"

    def test_expired_and_wrong_workspace(self):
        token = _make_token({"sub": "user1", "exp": 1000, "workspace": "wrong"})
        claims, err = validate_worker_token(token, now=1500, workspace="correct")
        assert err == "token expired"

    def test_anonymous_and_expired(self):
        """Anonymous check runs after time checks, so expired wins first."""
        token = _make_token({"sub": "anonymous", "exp": 1000})
        claims, err = validate_worker_token(token, now=1500)
        assert err == "token expired"

    def test_valid_token_with_all_checks(self):
        token = _make_token({
            "sub": "worker-42",
            "nbf": 1000,
            "exp": 2000,
            "scopes": ["worker:execute"],
            "workspace": "ws-prod",
        })
        claims, err = validate_worker_token(
            token,
            now=1500,
            required_scope="worker:execute",
            workspace="ws-prod",
        )
        assert err is None
        assert claims["sub"] == "worker-42"
        assert claims["workspace"] == "ws-prod"
