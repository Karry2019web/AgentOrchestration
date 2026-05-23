"""Tests for integration auth middleware — disabled user and credential validation."""

import pytest
import time
import json
import base64

from src.api.middleware import (
    AuthMiddleware,
    IntegrationAuthStore,
    integration_auth_store,
    _is_webhook_management_path,
    _extract_user_id,
    _hash_token,
    WEBHOOK_MANAGEMENT_PATHS,
)
from src.common.errors import (
    DisabledUserError,
    RevokedTokenError,
    InsufficientScopeError,
)


class TestIntegrationAuthStore:
    def setup_method(self):
        self.store = IntegrationAuthStore()

    def test_disable_and_check_user(self):
        self.store.disable_user("user-123")
        assert self.store.is_user_disabled("user-123") is True
        assert self.store.is_user_disabled("user-456") is False

    def test_enable_user(self):
        self.store.disable_user("user-123")
        assert self.store.is_user_disabled("user-123") is True
        self.store.enable_user("user-123")
        assert self.store.is_user_disabled("user-123") is False

    def test_revoke_and_check_token(self):
        self.store.revoke_token("abc123hash")
        assert self.store.is_token_revoked("abc123hash") is True
        assert self.store.is_token_revoked("otherhash") is False

    def test_token_expiry(self):
        token_hash = "token1"
        self.store.set_token_expiry(token_hash, time.time() + 3600)
        assert self.store.is_token_expired(token_hash) is False

        self.store.set_token_expiry(token_hash, time.time() - 10)
        assert self.store.is_token_expired(token_hash) is True

    def test_credential_valid_all_pass(self):
        user = "user-valid"
        token = "tok-hash-valid"
        assert self.store.is_credential_valid(user, token) is True

    def test_credential_invalid_disabled_user(self):
        self.store.disable_user("user-disabled")
        assert self.store.is_credential_valid("user-disabled", "any-token") is False

    def test_credential_invalid_revoked_token(self):
        self.store.revoke_token("revoked-token")
        assert self.store.is_credential_valid("any-user", "revoked-token") is False

    def test_credential_invalid_expired_token(self):
        self.store.set_token_expiry("expired-token", time.time() - 1)
        assert self.store.is_credential_valid("any-user", "expired-token") is False


class TestWebhookPathDetection:
    def test_webhook_paths_detected(self):
        assert _is_webhook_management_path("/api/v2/webhooks") is True
        assert _is_webhook_management_path("/api/v2/webhooks/subscriptions") is True
        assert _is_webhook_management_path("/api/v2/integrations/webhook") is True
        assert _is_webhook_management_path("/api/v2/integrations") is True
        assert _is_webhook_management_path("/api/v2/integrations/slack") is True

    def test_non_webhook_paths_not_detected(self):
        assert _is_webhook_management_path("/api/v2/agents") is False
        assert _is_webhook_management_path("/api/v2/auth/token") is False
        assert _is_webhook_management_path("/health") is False
        assert _is_webhook_management_path("/api/v1/webhooks") is False


class TestTokenExtraction:
    def test_extract_user_id_from_jwt_like_token(self):
        payload = {"sub": "user-789", "role": "admin"}
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        token = f"header.{encoded}.signature"
        assert _extract_user_id(token) == "user-789"

    def test_extract_user_id_from_malformed_token(self):
        assert _extract_user_id("not-a-valid-token") is None
        assert _extract_user_id("") is None

    def test_token_hash_consistency(self):
        t1 = _hash_token("my-api-key-123")
        t2 = _hash_token("my-api-key-123")
        t3 = _hash_token("different-key")
        assert t1 == t2
        assert t1 != t3


class TestErrorClasses:
    def test_disabled_user_error(self):
        err = DisabledUserError("user-blocked")
        assert "user-blocked" in str(err)
        assert "disabled" in str(err).lower()

    def test_revoked_token_error(self):
        err = RevokedTokenError()
        assert "revoked" in str(err).lower()
        assert "expired" in str(err).lower()

    def test_insufficient_scope_error(self):
        err = InsufficientScopeError("webhook:write")
        assert "webhook:write" in str(err)
        assert "Insufficient scope" in str(err)
