"""Tests for auth service — covers key validation, revocation, scope checks, and long-polling revalidation."""

import time
import pytest
from src.common.auth_service import (
    ApiKeyService,
    KeyStatus,
    Scope,
    api_key_service,
)


class TestApiKeyService:
    def setup_method(self):
        self.service = ApiKeyService()

    # --- Key status validation ---

    def test_valid_active_key(self):
        valid, reason, data = self.service.validate_key("sk-valid-admin-key-001")
        assert valid is True
        assert reason == "OK"
        assert data["user"] == "admin-user"

    def test_revoked_key_rejected(self):
        valid, reason, data = self.service.validate_key("sk-revoked-key-003")
        assert valid is False
        assert "revoked" in reason.lower()
        assert "User deactivated" in reason

    def test_expired_key_rejected(self):
        valid, reason, data = self.service.validate_key("sk-expired-key-004")
        assert valid is False
        assert "expired" in reason.lower()

    def test_disabled_key_rejected(self):
        valid, reason, data = self.service.validate_key("sk-disabled-key-005")
        assert valid is False
        assert "disabled" in reason.lower()

    def test_unknown_key_rejected(self):
        valid, reason, data = self.service.validate_key("sk-nonexistent-key-999")
        assert valid is False
        assert "Unknown" in reason

    # --- Scope enforcement ---

    def test_sufficient_scope_allowed(self):
        valid, reason, data = self.service.validate_key(
            "sk-valid-worker-key-002", required_scope=Scope.TASK_MONITOR
        )
        assert valid is True

    def test_insufficient_scope_rejected(self):
        valid, reason, data = self.service.validate_key(
            "sk-insufficient-key-006", required_scope=Scope.TASK_MONITOR
        )
        assert valid is False
        assert "lacks required scope" in reason.lower()
        assert "task:monitor" in reason

    def test_no_scopes_anon_key_rejected(self):
        valid, reason, data = self.service.validate_key(
            "sk-anon-key-007", required_scope=Scope.READ
        )
        assert valid is False
        assert "lacks required scope" in reason.lower()

    def test_admin_key_all_scopes_allowed(self):
        for scope in Scope:
            valid, _, _ = self.service.validate_key(
                "sk-valid-admin-key-001", required_scope=scope
            )
            assert valid is True, f"Admin key should have scope {scope.value}"

    # --- Dynamic revocation ---

    def test_key_revoked_mid_session_rejected(self):
        # Simulate a key that was valid being revoked (like during long-polling)
        key = "sk-valid-worker-key-002"
        # Initially valid
        valid, _, _ = self.service.validate_key(key)
        assert valid is True

        # Revoke it
        self.service.revoke_key(key, reason="Session terminated")

        # Now it should be rejected
        valid, reason, _ = self.service.validate_key(key)
        assert valid is False
        assert "revoked" in reason.lower()
        assert "Session terminated" in reason

    def test_revocation_log_tracking(self):
        key = "sk-valid-worker-key-002"
        before = time.time()
        self.service.revoke_key(key, reason="Test revocation")
        after = time.time()

        # Check log for entries since 'before'
        revoked_keys = self.service.get_revocation_log(before - 1)
        assert key in revoked_keys

        # Check log for entries since 'after' (should be empty for this key next time)
        revoked_keys_after = self.service.get_revocation_log(after + 1)
        # Could include other keys in the next entries, but at minimum our entry is before 'after'

    # --- Long-polling re-validation ---

    def test_long_polling_revalidates_on_every_call(self):
        """Simulate a long-polling connection where key is revoked mid-stream."""
        key = "sk-valid-worker-key-002"

        # Call 1: valid (simulating first poll)
        assert self.service.check_key_still_valid(key) is True

        # Revoke happens between polls
        self.service.revoke_key(key, reason="Admin revoked session")

        # Call 2: should be rejected (simulating next poll)
        assert self.service.check_key_still_valid(key) is False

    def test_long_polling_expired_key_detected(self):
        """Keys that expire between long-polling calls should be rejected."""
        key = "sk-expired-key-004"
        assert self.service.check_key_still_valid(key) is False

    # --- Edge cases ---

    def test_empty_key_rejected(self):
        valid, reason, _ = self.service.validate_key("")
        assert valid is False

    def test_none_key_rejected(self):
        valid, reason, _ = self.service.validate_key(None)
        assert valid is False
        assert "Unknown" in reason

    def test_revoke_nonexistent_key(self):
        result = self.service.revoke_key("sk-does-not-exist")
        assert result is False

    def test_multiple_revocations_tracked(self):
        self.service.revoke_key("sk-valid-admin-key-001", reason="Rotation")
        self.service.revoke_key("sk-valid-worker-key-002", reason="Compromised")
        log = self.service.get_revocation_log(0)
        assert "sk-valid-admin-key-001" in log
        assert "sk-valid-worker-key-002" in log


class TestScopeMap:
    """Verify the scope mapping used by middleware covers known paths."""

    def test_task_monitor_path_requires_task_monitor_scope(self):
        from src.common.auth_service import get_required_scope
        scope = get_required_scope("/api/v2/tasks")
        assert scope == Scope.TASK_MONITOR
        scope = get_required_scope("/api/v2/tasks/1234")
        assert scope == Scope.TASK_MONITOR

    def test_agent_path_requires_agent_manage_scope(self):
        from src.common.auth_service import get_required_scope
        scope = get_required_scope("/api/v2/agents")
        assert scope == Scope.AGENT_MANAGE
        scope = get_required_scope("/api/v2/agents/test-agent")
        assert scope == Scope.AGENT_MANAGE

    def test_health_path_no_scope(self):
        from src.common.auth_service import get_required_scope
        scope = get_required_scope("/health")
        assert scope is None

    def test_unknown_path_no_scope(self):
        from src.common.auth_service import get_required_scope
        scope = get_required_scope("/api/v2/unknown")
        assert scope is None
