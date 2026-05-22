"""Tests for blocking disabled users from webhook management (bounty #1971).

Acceptance Criteria:
- Tests prove stale, revoked, anonymous, and insufficiently scoped principals
  are denied from webhook management.
- Authorized users with the correct workspace role still manage webhooks
  successfully.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.common.auth import APIKey, APIKeyManager, APIKeyScope
from src.common.errors import AuthenticationError


class TestWebhookUserDisabled:
    """Disabled users are blocked from webhook management."""

    def setup_method(self):
        self.mgr = APIKeyManager()
        self.active_key = self.mgr.create_key(
            label="active-user",
            scopes=[APIKeyScope.READ, APIKeyScope.WRITE, APIKeyScope.MANAGE_WEBHOOKS],
            created_by="user-active",
        )
        self.mgr.index_token("sk-active-token", self.active_key.key_id)

        self.disabled_user_key = self.mgr.create_key(
            label="disabled-user",
            scopes=[APIKeyScope.READ, APIKeyScope.WRITE, APIKeyScope.MANAGE_WEBHOOKS],
            created_by="user-disabled",
        )
        self.mgr.index_token("sk-disabled-token", self.disabled_user_key.key_id)
        self.mgr.disable_user("user-disabled")

        self.revoked_key = self.mgr.create_key(
            label="revoked-key",
            scopes=[APIKeyScope.READ, APIKeyScope.WRITE, APIKeyScope.MANAGE_WEBHOOKS],
            created_by="user-revoked",
        )
        self.mgr.index_token("sk-revoked-token", self.revoked_key.key_id)
        self.mgr.revoke_key(self.revoked_key.key_id, by="admin")

        self.ro_key = self.mgr.create_key(
            label="readonly",
            scopes=[APIKeyScope.READ],
            created_by="user-readonly",
        )
        self.mgr.index_token("sk-readonly-webhook", self.ro_key.key_id)

    def _patch_key_manager(self):
        """Patch the global key_manager with our test manager."""
        import src.webhooks.manager as whm
        original = whm.key_manager
        whm.key_manager = self.mgr
        import src.common.auth as cauth
        cauth.key_manager = self.mgr
        return original

    def _restore_key_manager(self, original):
        import src.webhooks.manager as whm
        import src.common.auth as cauth
        whm.key_manager = original
        cauth.key_manager = original

    # ── Active user can manage webhooks ───────────────────────────

    def test_active_user_can_access_webhooks(self):
        """Authorized users with correct role still manage webhooks successfully."""
        from src.webhooks.manager import WebhookAuth

        orig = self._patch_key_manager()
        try:
            user_id = WebhookAuth.ensure_user_active("Bearer sk-active-token")
            assert user_id == "user-active"
        finally:
            self._restore_key_manager(orig)

    def test_active_user_can_create_webhook(self):
        """Active user can create a webhook subscription."""
        from src.webhooks.manager import WebhookManager

        orig = self._patch_key_manager()
        try:
            wm = WebhookManager()
            result = wm.create_subscription(
                url="https://example.com/hooks",
                event_types=["task.completed"],
                token="Bearer sk-active-token",
            )
            assert result["created_by"] == "user-active"
            assert result["url"] == "https://example.com/hooks"
        finally:
            self._restore_key_manager(orig)

    # ── Disabled user is blocked ──────────────────────────────────

    def test_disabled_user_cannot_access_webhooks(self):
        """Tests prove disabled user principals are denied."""
        from src.webhooks.manager import WebhookAuth

        orig = self._patch_key_manager()
        try:
            with pytest.raises(AuthenticationError, match="disabled"):
                WebhookAuth.ensure_user_active("Bearer sk-disabled-token")
        finally:
            self._restore_key_manager(orig)

    def test_disabled_user_cannot_create_webhook(self):
        """Disabled user cannot create a webhook subscription."""
        from src.webhooks.manager import WebhookManager

        orig = self._patch_key_manager()
        try:
            wm = WebhookManager()
            with pytest.raises(AuthenticationError, match="disabled"):
                wm.create_subscription(
                    url="https://example.com/hooks",
                    event_types=["task.completed"],
                    token="Bearer sk-disabled-token",
                )
        finally:
            self._restore_key_manager(orig)

    def test_disabled_user_cannot_delete_webhook(self):
        """Disabled user cannot delete a webhook subscription."""
        from src.webhooks.manager import WebhookManager

        orig = self._patch_key_manager()
        try:
            wm = WebhookManager()
            # Create a subscription as active user first
            sub = wm.create_subscription(
                url="https://example.com/hooks",
                event_types=["task.completed"],
                token="Bearer sk-active-token",
            )
            sub_id = sub["subscription_id"]

            # Try to delete as disabled user
            with pytest.raises(AuthenticationError, match="disabled"):
                wm.delete_subscription(sub_id, "Bearer sk-disabled-token")
        finally:
            self._restore_key_manager(orig)

    # ── Revoked key is blocked ────────────────────────────────────

    def test_revoked_key_cannot_access_webhooks(self):
        """Tests prove revoked principals are denied."""
        from src.webhooks.manager import WebhookAuth

        orig = self._patch_key_manager()
        try:
            with pytest.raises(AuthenticationError, match="revoked"):
                WebhookAuth.ensure_user_active("Bearer sk-revoked-token")
        finally:
            self._restore_key_manager(orig)

    # ── Anonymous is blocked ──────────────────────────────────────

    def test_anonymous_cannot_access_webhooks(self):
        """Tests prove anonymous principals are denied."""
        from src.webhooks.manager import WebhookAuth

        orig = self._patch_key_manager()
        try:
            with pytest.raises(AuthenticationError, match="Missing"):
                WebhookAuth.ensure_user_active("")
        finally:
            self._restore_key_manager(orig)

    def test_unknown_token_cannot_access_webhooks(self):
        """Tests prove unknown tokens are denied."""
        from src.webhooks.manager import WebhookAuth

        orig = self._patch_key_manager()
        try:
            with pytest.raises(AuthenticationError, match="Unknown|denied"):
                WebhookAuth.ensure_user_active("Bearer sk-no-such-key")
        finally:
            self._restore_key_manager(orig)

    # ── Insufficient scope is blocked ─────────────────────────────

    def test_insufficient_scope_cannot_access_webhooks(self):
        """Tests prove insufficiently scoped principals are denied."""
        from src.webhooks.manager import WebhookAuth

        orig = self._patch_key_manager()
        try:
            with pytest.raises(AuthenticationError, match="scope"):
                WebhookAuth.ensure_user_active("Bearer sk-readonly-webhook")
        finally:
            self._restore_key_manager(orig)
