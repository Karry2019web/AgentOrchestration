"""Tests for operator token authentication and least-privilege scope enforcement."""

import time
import json
import pytest

from src.common.auth import (
    OperatorTokenService,
    SessionStore,
    TokenScope,
    TokenValidationResult,
    TokenPayload,
)


# ============================================================
# SessionStore Tests
# ============================================================

class TestSessionStore:
    def setup_method(self):
        self.store = SessionStore()

    def test_revoke_and_check(self):
        self.store.revoke("token-123")
        assert self.store.is_revoked("token-123") is True
        assert self.store.is_revoked("token-456") is False

    def test_register_and_get_session(self):
        self.store.register_session("token-1", {"user": "alice", "workspace": "ws-1"})
        session = self.store.get_session("token-1")
        assert session["user"] == "alice"
        assert session["workspace"] == "ws-1"

    def test_remove_session(self):
        self.store.register_session("token-1", {"user": "alice"})
        self.store.remove_session("token-1")
        assert self.store.get_session("token-1") is None
        assert self.store.is_revoked("token-1") is True


# ============================================================
# OperatorTokenService Tests
# ============================================================

class TestOperatorTokenService:
    def setup_method(self):
        self.service = OperatorTokenService(
            signing_key="test-key-12345",
            default_ttl=3600,
        )

    def test_create_token_valid(self):
        """Token creation produces a valid two-part token."""
        token = self.service.create_token(
            subject="user-1",
            workspace_id="ws-default",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        assert token.count(".") == 1
        assert len(token) > 20

    def test_validate_valid_token(self):
        """A freshly created token validates as VALID."""
        token = self.service.create_token(
            subject="user-1",
            workspace_id="ws-default",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        result = self.service.validate_token(token)
        assert result == TokenValidationResult.VALID

    def test_validate_expired_token(self):
        """An expired token must be rejected."""
        expired_service = OperatorTokenService(signing_key="test", default_ttl=-3600)
        token = expired_service.create_token(
            subject="user-1",
            workspace_id="ws-default",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        result = expired_service.validate_token(token)
        assert result == TokenValidationResult.EXPIRED

    def test_validate_malformed_token(self):
        """A garbage token string is MALFORMED."""
        result = self.service.validate_token("not-a-token")
        assert result == TokenValidationResult.MALFORMED

        result = self.service.validate_token("too.many.parts")
        assert result == TokenValidationResult.MALFORMED

    def test_validate_revoked_token(self):
        """A revoked token is REVOKED."""
        token = self.service.create_token(
            subject="user-1",
            workspace_id="ws-default",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        payload = self.service.decode_token(token)
        token_id = payload["jti"]
        self.service.revoke_token(token_id)
        result = self.service.validate_token(token)
        assert result == TokenValidationResult.REVOKED

    def test_validate_insufficient_scope(self):
        """A token without the required scope is INSUFFICIENT_SCOPE."""
        token = self.service.create_token(
            subject="user-1",
            workspace_id="ws-default",
            scopes=[TokenScope.RUN_READ.value],
        )
        result = self.service.validate_token(
            token,
            required_scopes={TokenScope.RUN_CANCEL.value},
        )
        assert result == TokenValidationResult.INSUFFICIENT_SCOPE

    def test_admin_token_has_all_scopes(self):
        """Admin-scoped token satisfies any scope requirement."""
        token = self.service.create_token(
            subject="admin-1",
            workspace_id="ws-default",
            scopes=[TokenScope.ADMIN.value],
        )
        result = self.service.validate_token(
            token,
            required_scopes={TokenScope.RUN_CANCEL.value},
        )
        assert result == TokenValidationResult.VALID

    def test_validate_anonymous_no_token(self):
        """An empty token string is MALFORMED (effectively anonymous rejection)."""
        result = self.service.validate_token("")
        assert result == TokenValidationResult.MALFORMED

    def test_validate_wrong_signature(self):
        """Token from a different service has wrong signature."""
        service_a = OperatorTokenService(signing_key="key-a")
        service_b = OperatorTokenService(signing_key="key-b")
        token = service_a.create_token(
            subject="user-1", workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        result = service_b.validate_token(token)
        assert result == TokenValidationResult.MALFORMED

    def test_tampered_payload_rejected(self):
        """Token with tampered payload is MALFORMED."""
        token = self.service.create_token(
            subject="user-1", workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        parts = token.split(".")
        import base64
        import json
        # Replace with a different payload
        fake_payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "attacker", "ws": "ws-1", "scp": ["run:cancel"]}).encode()
        ).rstrip(b"=").decode()
        tampered = f"{fake_payload}.{parts[1]}"
        result = self.service.validate_token(tampered)
        assert result == TokenValidationResult.MALFORMED

    def test_decode_token_payload(self):
        """Decoded token payload contains expected fields."""
        token = self.service.create_token(
            subject="user-1",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value, TokenScope.RUN_READ.value],
            metadata={"env": "staging"},
        )
        payload = self.service.decode_token(token)
        assert payload["sub"] == "user-1"
        assert payload["ws"] == "ws-1"
        assert TokenScope.RUN_CANCEL.value in payload["scp"]
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload
        assert payload["meta"]["env"] == "staging"


# ============================================================
# Run Cancellation - Least-Privilege Enforcement Tests
# ============================================================

class TestRunCancellationAuth:
    """Core tests for the bounty issue: enforcing least-privilege
    scopes on run cancellation."""

    def setup_method(self):
        self.service = OperatorTokenService(
            signing_key="test-run-cancel-key",
            default_ttl=3600,
        )

    def test_valid_run_cancellation_succeeds(self):
        """Authorized user with run:cancel scope can cancel in their workspace."""
        token = self.service.create_token(
            subject="operator-1",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        result = self.service.validate_run_cancellation(token, agent_workspace="ws-1")
        assert result == TokenValidationResult.VALID

    def test_stale_expired_token_rejected(self):
        """Stale (expired) token must be denied."""
        expired_service = OperatorTokenService(signing_key="test", default_ttl=-3600)
        token = expired_service.create_token(
            subject="operator-1",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        result = expired_service.validate_run_cancellation(token, agent_workspace="ws-1")
        assert result == TokenValidationResult.EXPIRED

    def test_revoked_token_rejected(self):
        """Revoked token must be denied."""
        token = self.service.create_token(
            subject="operator-1",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        payload = self.service.decode_token(token)
        self.service.revoke_token(payload["jti"])
        result = self.service.validate_run_cancellation(token, agent_workspace="ws-1")
        assert result == TokenValidationResult.REVOKED

    def test_anonymous_token_rejected(self):
        """Empty/malformed token is denied (effectively anonymous)."""
        result = self.service.validate_run_cancellation("", agent_workspace="ws-1")
        assert result == TokenValidationResult.MALFORMED

    def test_insufficiently_scoped_principal_denied(self):
        """Token with only run:read scope cannot cancel."""
        token = self.service.create_token(
            subject="operator-1",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_READ.value],
        )
        result = self.service.validate_run_cancellation(token, agent_workspace="ws-1")
        assert result == TokenValidationResult.INSUFFICIENT_SCOPE

    def test_wrong_workspace_denied(self):
        """Token from workspace-1 cannot cancel runs in workspace-2."""
        token = self.service.create_token(
            subject="operator-1",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        result = self.service.validate_run_cancellation(token, agent_workspace="ws-2")
        assert result == TokenValidationResult.WRONG_WORKSPACE

    def test_admin_can_cancel_in_same_workspace(self):
        """Admin token can cancel runs in the same workspace."""
        token = self.service.create_token(
            subject="admin-1",
            workspace_id="ws-1",
            scopes=[TokenScope.ADMIN.value],
        )
        result = self.service.validate_run_cancellation(token, agent_workspace="ws-1")
        assert result == TokenValidationResult.VALID

    def test_malformed_signature_rejected(self):
        """A token with tampered signature is malformed."""
        token = self.service.create_token(
            subject="operator-1",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        parts = token.split(".")
        tampered = parts[0] + ".invalidsignature"
        result = self.service.validate_run_cancellation(tampered, agent_workspace="ws-1")
        assert result == TokenValidationResult.MALFORMED

    def test_user_without_run_cancel_but_with_agent_write_denied(self):
        """Token with agent:write but NOT run:cancel cannot cancel a run."""
        token = self.service.create_token(
            subject="operator-1",
            workspace_id="ws-1",
            scopes=[TokenScope.AGENT_WRITE.value],
        )
        result = self.service.validate_run_cancellation(token, agent_workspace="ws-1")
        assert result == TokenValidationResult.INSUFFICIENT_SCOPE


# ============================================================
# TokenPayload Tests
# ============================================================

class TestTokenPayload:
    def test_is_expired(self):
        past = time.time() - 1000
        payload = TokenPayload(
            subject="user",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
            issued_at=past - 3600,
            expires_at=past,
            token_id="tid-1",
        )
        assert payload.is_expired() is True

    def test_is_not_expired(self):
        future = time.time() + 3600
        payload = TokenPayload(
            subject="user",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
            issued_at=time.time(),
            expires_at=future,
            token_id="tid-2",
        )
        assert payload.is_expired() is False

    def test_has_scope(self):
        payload = TokenPayload(
            subject="user",
            workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
            issued_at=time.time(),
            expires_at=time.time() + 3600,
            token_id="tid-3",
        )
        assert payload.has_scope(TokenScope.RUN_CANCEL.value) is True
        assert payload.has_scope(TokenScope.AGENT_DELETE.value) is False

    def test_admin_has_any_scope(self):
        payload = TokenPayload(
            subject="admin",
            workspace_id="ws-1",
            scopes=[TokenScope.ADMIN.value],
            issued_at=time.time(),
            expires_at=time.time() + 3600,
            token_id="tid-4",
        )
        assert payload.has_scope(TokenScope.RUN_CANCEL.value) is True
        assert payload.has_scope(TokenScope.AGENT_DELETE.value) is True


# ============================================================
# get_token_payload Tests
# ============================================================

class TestGetTokenPayload:
    def setup_method(self):
        self.service = OperatorTokenService(signing_key="test-payload", default_ttl=3600)

    def test_valid_token_returns_payload(self):
        token = self.service.create_token(
            subject="user-1", workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        payload = self.service.get_token_payload(token)
        assert payload is not None
        assert payload.subject == "user-1"
        assert payload.workspace_id == "ws-1"
        assert TokenScope.RUN_CANCEL.value in payload.scopes

    def test_expired_token_returns_none(self):
        service = OperatorTokenService(signing_key="test-payload", default_ttl=-3600)
        token = service.create_token(
            subject="user-1", workspace_id="ws-1",
            scopes=[TokenScope.RUN_CANCEL.value],
        )
        payload = service.get_token_payload(token)
        assert payload is None

    def test_invalid_token_returns_none(self):
        payload = self.service.get_token_payload("invalid-token")
        assert payload is None
