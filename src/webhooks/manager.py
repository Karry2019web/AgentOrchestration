"""Webhook subscription management with user-disabled enforcement.

Addresses the bug: disabled users can still manage webhooks because
the integration auth layer does not check user disablement status.
"""

import time
import uuid
import logging
from typing import Any, Dict, List, Optional

from src.common.auth import APIKeyScope, key_manager
from src.common.errors import AuthenticationError

logger = logging.getLogger(__name__)


class WebhookSubscription:
    """A webhook subscription tied to a user and workspace."""

    def __init__(
        self,
        url: str,
        event_types: List[str],
        created_by: str,
        workspace_id: str,
        subscription_id: Optional[str] = None,
    ):
        self.subscription_id = subscription_id or str(uuid.uuid4())
        self.url = url
        self.event_types = event_types
        self.created_by = created_by
        self.workspace_id = workspace_id
        self.created_at = time.time()
        self.active = True

    def to_dict(self) -> Dict:
        return {
            "subscription_id": self.subscription_id,
            "url": self.url,
            "event_types": self.event_types,
            "created_by": self.created_by,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at,
            "active": self.active,
        }


class WebhookAuth:
    """Enforce that only non-disabled users can manage webhooks.

    Wraps every webhook-management operation with a user-disabled check
    so that calling e.g. ``create_subscription`` with a disabled user's
    token raises ``AuthenticationError``.
    """

    @staticmethod
    def ensure_user_active(token: str) -> str:
        """Raise if the token belongs to a disabled user; return user_id otherwise."""
        result = key_manager.validate(token, APIKeyScope.MANAGE_WEBHOOKS)
        if not result:
            raise AuthenticationError(
                f"Webhook management denied: {result.reason}"
            )
        # Extra guard: even if key is valid, check user disablement
        if result.key and key_manager.is_user_disabled(result.key.created_by):
            raise AuthenticationError(
                "Webhook management denied: user account is disabled"
            )
        return result.key.created_by if result.key else ""

    @staticmethod
    def authorize_create(url: str, event_types: List[str], token: str) -> str:
        """Authorize creating a webhook subscription. Returns user_id."""
        return WebhookAuth.ensure_user_active(token)

    @staticmethod
    def authorize_delete(subscription_id: str, token: str, owner: str) -> str:
        """Authorize deleting a webhook subscription. Returns user_id."""
        user_id = WebhookAuth.ensure_user_active(token)
        if user_id != owner:
            raise AuthenticationError(
                "Webhook management denied: can only manage own subscriptions"
            )
        return user_id

    @staticmethod
    def authorize_list(token: str) -> str:
        """Authorize listing webhook subscriptions. Returns user_id."""
        return WebhookAuth.ensure_user_active(token)


class WebhookManager:
    """Manages webhook subscriptions with user-disabled enforcement."""

    def __init__(self):
        self._subscriptions: Dict[str, WebhookSubscription] = {}
        self._user_subs: Dict[str, List[str]] = {}

    def create_subscription(
        self, url: str, event_types: List[str], token: str
    ) -> Dict:
        user_id = WebhookAuth.authorize_create(url, event_types, token)
        sub = WebhookSubscription(
            url=url,
            event_types=event_types,
            created_by=user_id,
            workspace_id="default",
        )
        self._subscriptions[sub.subscription_id] = sub
        if user_id not in self._user_subs:
            self._user_subs[user_id] = []
        self._user_subs[user_id].append(sub.subscription_id)
        logger.info(f"Webhook {sub.subscription_id} created by {user_id}")
        return sub.to_dict()

    def delete_subscription(self, subscription_id: str, token: str) -> bool:
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            return False
        WebhookAuth.authorize_delete(subscription_id, token, sub.created_by)
        del self._subscriptions[subscription_id]
        user_subs = self._user_subs.get(sub.created_by, [])
        if subscription_id in user_subs:
            user_subs.remove(subscription_id)
        logger.info(f"Webhook {subscription_id} deleted")
        return True

    def list_subscriptions(self, token: str) -> List[Dict]:
        user_id = WebhookAuth.authorize_list(token)
        sub_ids = self._user_subs.get(user_id, [])
        return [
            self._subscriptions[sid].to_dict()
            for sid in sub_ids
            if sid in self._subscriptions
        ]

    def get_subscription(self, subscription_id: str) -> Optional[WebhookSubscription]:
        return self._subscriptions.get(subscription_id)
