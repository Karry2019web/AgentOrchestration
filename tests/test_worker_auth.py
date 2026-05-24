"""Tests for worker authentication utilities."""

import time
import json
import base64
import pytest
from src.common.auth import (
    decode_jwt_payload,
    validate_worker_token,
    MalformedTokenError,
    TokenNotYetValidError,
    TokenExpiredError,
    InvalidSubjectError,
    InsufficientScopeError,
    WorkspaceMismatchError,
)


def _make_jwt(payload: dict) -> str:
    """Create an unsigned JWT token string for testing."""
    header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header_b64}.{payload_b64}.{sig_b64}"


# --- decode_jwt_payload ---

class TestDecodeJwtPayload:
    def test_valid_token(self):
        payload = {"sub": "worker-01", "scope": "worker"}
        token = _make_jwt(payload)
        result = decode_jwt_payload(token)
        assert result == payload

    def test_malformed_token_too_few_parts(self):
        assert decode_jwt_payload("abc.def") is None

    def test_malformed_token_too_many_parts(self):
        assert decode_jwt_payload("a.b.c.d") is None

    def test_empty_token(self):
        assert decode_jwt_payload("") is None

    def test_invalid_base64_payload(self):
        token = "header.!!!invalid!!!.sig"
        result = decode_jwt_payload(token)
        assert result is None

    def test_non_json_payload(self):
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(b"not-json").rstrip(b"=").decode()
        token = f"{header}.{payload}.sig"
        assert decode_jwt_payload(token) is None

    def test_payload_with_nbf_and_exp(self):
        now = time.time()
        payload = {"sub": "w-1", "nbf": now - 100, "exp": now + 3600}
        token = _make_jwt(payload)
        result = decode_jwt_payload(token)
        assert result["sub"] == "w-1"
        assert "nbf" in result
        assert "exp" in result


# --- validate_worker_token ---

class TestValidateWorkerToken:
    def test_valid_token_passes(self):
        now = time.time()
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": now - 60,
            "exp": now + 3600,
            "scope": "worker",
        })
        result = validate_worker_token(f"Bearer {token}")
        assert result["sub"] == "worker-01"

    def test_malformed_token_no_bearer_prefix(self):
        with pytest.raises(MalformedTokenError):
            validate_worker_token("NotBearer token")

    def test_empty_authorization_header(self):
        with pytest.raises(MalformedTokenError):
            validate_worker_token("Bearer ")

    def test_missing_token(self):
        with pytest.raises(MalformedTokenError):
            validate_worker_token("")

    def test_nbf_in_future_denied(self):
        future = time.time() + 3600
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": future,
            "exp": time.time() + 7200,
            "scope": "worker",
        })
        with pytest.raises(TokenNotYetValidError):
            validate_worker_token(f"Bearer {token}")

    def test_nbf_within_clock_skew_allowed(self):
        near_future = time.time() + 10
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": near_future,
            "exp": time.time() + 7200,
            "scope": "worker",
        })
        result = validate_worker_token(f"Bearer {token}", max_clock_skew=30)
        assert result["sub"] == "worker-01"

    def test_expired_token_denied(self):
        past = time.time() - 7200
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 14400,
            "exp": past,
            "scope": "worker",
        })
        with pytest.raises(TokenExpiredError):
            validate_worker_token(f"Bearer {token}")

    def test_token_expired_within_clock_skew_allowed(self):
        just_past = time.time() - 10
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 7200,
            "exp": just_past,
            "scope": "worker",
        })
        result = validate_worker_token(f"Bearer {token}", max_clock_skew=30)
        assert result["sub"] == "worker-01"

    def test_empty_subject_denied(self):
        token = _make_jwt({
            "sub": "",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
        })
        with pytest.raises(InvalidSubjectError):
            validate_worker_token(f"Bearer {token}")

    def test_anonymous_subject_denied(self):
        token = _make_jwt({
            "sub": "anonymous",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
        })
        with pytest.raises(InvalidSubjectError):
            validate_worker_token(f"Bearer {token}")

    def test_guest_subject_denied(self):
        token = _make_jwt({
            "sub": "guest",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
        })
        with pytest.raises(InvalidSubjectError):
            validate_worker_token(f"Bearer {token}")

    def test_anon_subject_denied(self):
        token = _make_jwt({
            "sub": "anon",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
        })
        with pytest.raises(InvalidSubjectError):
            validate_worker_token(f"Bearer {token}")

    def test_missing_subject_denied(self):
        token = _make_jwt({
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
        })
        with pytest.raises(InvalidSubjectError):
            validate_worker_token(f"Bearer {token}")

    def test_missing_scope_denied(self):
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
        })
        with pytest.raises(InsufficientScopeError):
            validate_worker_token(f"Bearer {token}")

    def test_wrong_scope_denied(self):
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "admin",
        })
        with pytest.raises(InsufficientScopeError):
            validate_worker_token(f"Bearer {token}", required_scope="worker")

    def test_scope_as_string_with_multiple_values(self):
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker admin",
        })
        result = validate_worker_token(f"Bearer {token}", required_scope="worker")
        assert result["sub"] == "worker-01"

    def test_workspace_mismatch_denied(self):
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
            "workspace_id": "ws-alpha",
        })
        with pytest.raises(WorkspaceMismatchError):
            validate_worker_token(f"Bearer {token}", workspace_id="ws-beta")

    def test_workspace_match_passes(self):
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
            "workspace_id": "ws-alpha",
        })
        result = validate_worker_token(f"Bearer {token}", workspace_id="ws-alpha")
        assert result["sub"] == "worker-01"

    def test_workspace_check_with_workspace_key(self):
        """Test workspace_id field can also use 'workspace' key."""
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
            "workspace": "ws-alpha",
        })
        result = validate_worker_token(f"Bearer {token}", workspace_id="ws-alpha")
        assert result["sub"] == "worker-01"

    def test_valid_token_no_workspace_check(self):
        """No workspace_id param means workspace is not validated."""
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 60,
            "exp": time.time() + 3600,
            "scope": "worker",
        })
        result = validate_worker_token(f"Bearer {token}")
        assert result["sub"] == "worker-01"

    def test_missing_nbf_allowed(self):
        token = _make_jwt({
            "sub": "worker-01",
            "exp": time.time() + 3600,
            "scope": "worker",
        })
        result = validate_worker_token(f"Bearer {token}")
        assert result["sub"] == "worker-01"

    def test_missing_exp_allowed(self):
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 60,
            "scope": "worker",
        })
        result = validate_worker_token(f"Bearer {token}")
        assert result["sub"] == "worker-01"

    def test_nbf_as_float(self):
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": time.time() - 30.5,
            "exp": time.time() + 3600,
            "scope": "worker",
        })
        result = validate_worker_token(f"Bearer {token}")
        assert result["sub"] == "worker-01"

    def test_additional_claims_preserved(self):
        now = time.time()
        token = _make_jwt({
            "sub": "worker-01",
            "nbf": now - 60,
            "exp": now + 3600,
            "scope": "worker",
            "agent_id": "ag-001",
            "role": "executor",
            "metadata": {"env": "prod"},
        })
        result = validate_worker_token(f"Bearer {token}")
        assert result["agent_id"] == "ag-001"
        assert result["role"] == "executor"
        assert result["metadata"] == {"env": "prod"}


# 2026-05-24T08:00:00Z update
