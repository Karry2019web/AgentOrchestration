"""Webhook subscription filter validation and delivery helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


ALLOWED_FILTER_FIELDS: Set[str] = {
    "event_id",
    "event_type",
    "workspace_id",
    "status",
    "agent_id",
}

INTERNAL_ONLY_FIELDS: Set[str] = {
    "internal_token",
    "secret",
    "trace_id",
    "database_uri",
    "api_key",
}


class WebhookError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class WebhookSubscription:
    subscription_id: str
    workspace_id: str
    target_url: str
    filters: Dict[str, Any]
    enabled: bool = True


class WebhookService:
    def __init__(self):
        self._subscriptions: Dict[str, WebhookSubscription] = {}

    def clear(self) -> None:
        self._subscriptions.clear()

    def _validate_filters(self, filters: Dict[str, Any]) -> None:
        """Validate subscription filters against allowed fields.
        
        Raises WebhookError if any filter key is not in the allowed set.
        """
        if not isinstance(filters, dict):
            raise WebhookError(400, "Filters must be a mapping of field -> expected value")
        invalid = [k for k in filters if k not in ALLOWED_FILTER_FIELDS]
        if invalid:
            raise WebhookError(
                422,
                f"Unsupported subscription filter field(s): {', '.join(sorted(invalid))}",
            )

    def _validate_target_url(self, target_url: str) -> None:
        if not target_url.startswith("https://"):
            raise WebhookError(400, "Webhook target URL must use https://")

    def create_subscription(
        self, workspace_id: str, target_url: str, filters: Dict[str, Any]
    ) -> WebhookSubscription:
        self._validate_target_url(target_url)
        self._validate_filters(filters)
        subscription = WebhookSubscription(
            subscription_id=str(uuid4()),
            workspace_id=workspace_id,
            target_url=target_url,
            filters=dict(filters),
        )
        self._subscriptions[subscription.subscription_id] = subscription
        return subscription

    def disable_subscription(self, subscription_id: str, workspace_id: str) -> WebhookSubscription:
        sub = self._get_owned_subscription(subscription_id, workspace_id)
        sub.enabled = False
        return sub

    def _get_owned_subscription(self, subscription_id: str, workspace_id: str) -> WebhookSubscription:
        sub = self._subscriptions.get(subscription_id)
        if sub is None:
            raise WebhookError(404, "Webhook subscription not found")
        if sub.workspace_id != workspace_id:
            raise WebhookError(403, "Workspace access denied")
        return sub

    def matches_filters(self, subscription: WebhookSubscription, event: Dict[str, Any]) -> bool:
        """Check if an event matches a subscription's filters.
        
        All filter conditions must match for the event to match.
        Events with no filters match all events.
        """
        self._validate_filters(subscription.filters)
        for field, expected in subscription.filters.items():
            if event.get(field) != expected:
                return False
        return True


webhooks = WebhookService()
