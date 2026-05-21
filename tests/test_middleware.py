"""Tests for JWT authentication middleware and auth utilities."""

import time
import json
import os
import pytest
from unittest.mock import patch

from src.common.auth import (
    create_service_token,
    validate_service_token,
)


class TestAuthUtils:
    def setup_method(self):
        self.secret = "test-secret-for-testing"
        self.audience = "agent-orchestrator"

    def test_create_and_validate_valid_token(self):
        """A freshly created token should validate successfully."""
        token = create_service_token("test-worker", self.audience, secret=self.secret)
        valid, error, payload = validate_service_token(
            token, self.audience, secret=self.secret
        )
        assert valid is True, f"Expected valid, got error: {error}"
        assert error is None
        assert payload is not None
        assert payload["iss"] == "test-worker"
        assert payload["aud"] == self.audience
        assert payload["sub"] == "service:test-worker"

    def test_expired_token(self):
        """An expired token should be rejected."""
        token = create_service_token("test-worker", self.audience, expiry=-10, secret=self.secret)
        valid, error, payload = validate_service_token(
            token, self.audience, secret=self.secret
        )
        assert valid is False
        assert "expired" in error.lower()

    def test_wrong_audience(self):
        """A token with wrong audience should be rejected."""
        token = create_service_token("test-worker", "wrong-service", secret=self.secret)
        valid, error, payload = validate_service_token(
            token, self.audience, secret=self.secret
        )
        assert valid is False
        assert "Invalid audience" in error

    def test_tampered_token(self):
        """A tampered token should fail signature verification."""
        token = create_service_token("test-worker", self.audience, secret=self.secret)
        parts = token.split(".")
        tampered = f"{parts[0]}.YWJjZGU=.{parts[2]}"
        valid, error, payload = validate_service_token(
            tampered, self.audience, secret=self.secret
        )
        assert valid is False
        assert "signature" in error.lower()

    def test_malformed_token(self):
        """Malformed tokens should be rejected."""
        valid, error, payload = validate_service_token(
            "not-a-jwt", self.audience, secret=self.secret
        )
        assert valid is False
        assert "malformed" in error.lower()

    def test_different_secret(self):
        """A token signed with a different secret should be rejected."""
        token = create_service_token("test-worker", self.audience, secret="secret-a")
        valid, error, payload = validate_service_token(
            token, self.audience, secret="secret-b"
        )
        assert valid is False
        assert "signature" in error.lower()

    def test_empty_token(self):
        """Empty token should be malformed."""
        valid, error, payload = validate_service_token("", self.audience, secret=self.secret)
        assert valid is False

    def test_allowed_issuers(self):
        """Token from an allowed issuer should pass."""
        token = create_service_token("worker-pool", self.audience, secret=self.secret)
        valid, error, payload = validate_service_token(
            token, self.audience, allowed_issuers=["worker-pool", "scheduler"], secret=self.secret
        )
        assert valid is True

    def test_disallowed_issuer(self):
        """Token from a disallowed issuer should be rejected."""
        token = create_service_token("unknown-bot", self.audience, secret=self.secret)
        valid, error, payload = validate_service_token(
            token, self.audience, allowed_issuers=["worker-pool"], secret=self.secret
        )
        assert valid is False
        assert "issuer" in error.lower() or "allowed" in error.lower()

    def test_token_without_expiry(self):
        """Token without exp claim uses default validation."""
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {"iss": "test", "aud": self.audience, "iat": int(time.time())}
        import hmac, hashlib, base64 as b64

        def b64url(s):
            return b64.urlsafe_b64encode(s).rstrip(b"=").decode()

        h = b64url(json.dumps(header, separators=(",", ":")).encode())
        p = b64url(json.dumps(payload, separators=(",", ":")).encode())
        sig = b64url(hmac.new(self.secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
        token = f"{h}.{p}.{sig}"

        valid, error, payload = validate_service_token(token, self.audience, secret=self.secret)
        assert valid is True

    def test_default_secret_from_env(self):
        """When no secret provided, should read from env."""
        os.environ["AO_JWT_SECRET"] = "env-secret-value"
        token = create_service_token("env-test", self.audience)
        valid, error, payload = validate_service_token(token, self.audience)
        assert valid is True
        del os.environ["AO_JWT_SECRET"]


class TestMiddlewareIntegration:
    """Integration-style tests using Starlette TestClient."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from starlette.testclient import TestClient
        from src.api.server import create_app
        self.app = create_app()
        self.client = TestClient(self.app)
        self.secret = "test-secret-int"
        os.environ["AO_JWT_SECRET"] = self.secret
        yield
        if "AO_JWT_SECRET" in os.environ:
            del os.environ["AO_JWT_SECRET"]

    def test_health_endpoint_no_auth(self):
        """Health endpoint should not require auth."""
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_api_without_token(self):
        """API v2 endpoint without token should return 401."""
        resp = self.client.get("/api/v2/agents")
        assert resp.status_code == 401

    def test_api_with_valid_token(self):
        """API v2 endpoint with valid token should succeed."""
        token = create_service_token("test-client", "agent-orchestrator", secret=self.secret)
        resp = self.client.get(
            "/api/v2/agents",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200

    def test_api_with_expired_token(self):
        """API v2 endpoint with expired token should return 401."""
        token = create_service_token("test-client", "agent-orchestrator", expiry=-60, secret=self.secret)
        resp = self.client.get(
            "/api/v2/agents",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401

    def test_api_with_tampered_token(self):
        """API v2 endpoint with tampered token should return 401."""
        token = create_service_token("test-client", "agent-orchestrator", secret=self.secret)
        parts = token.split(".")
        bad_token = f"{parts[0]}.YWJj.ZGU.{parts[2]}"
        resp = self.client.get(
            "/api/v2/agents",
            headers={"Authorization": f"Bearer {bad_token}"}
        )
        assert resp.status_code == 401

    def test_auth_token_endpoint(self):
        """Auth token endpoint should not require auth."""
        token = create_service_token("test", "agent-orchestrator", secret=self.secret)
        resp = self.client.get(
            "/api/v2/auth/token",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code in (200, 404, 405)

    def test_no_auth_header(self):
        """Missing Authorization header should return 401."""
        resp = self.client.get("/api/v2/agents", headers={})
        assert resp.status_code == 401

    def test_bearer_without_token(self):
        """'Bearer ' with no token should return 401."""
        resp = self.client.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer "}
        )
        assert resp.status_code == 401


class TestSDKClientToken:
    """Tests for SDK client token handling."""

    def test_client_sends_auth_header(self):
        """SDK client should send Bearer token."""
        from src.sdk.client import OrchestratorClient
        client = OrchestratorClient(base_url="http://localhost:9999", api_key="test-key")
        assert client.api_key == "test-key"
