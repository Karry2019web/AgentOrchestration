"""Webhook subscription management with URL normalization."""

import uuid
import time
from urllib.parse import urlparse, urlunparse
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


def normalize_webhook_url(url: str) -> str:
    """Normalize a webhook URL for consistent duplicate checking.
    
    - Lowercases scheme and hostname
    - Removes default ports (80 for http, 443 for https)
    - Removes trailing slash
    - Removes fragment
    - Sorts query parameters
    """
    if not url:
        raise ValueError("URL must not be empty")
    
    parsed = urlparse(url)
    
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {scheme}")
    
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if not hostname:
        raise ValueError("URL must have a hostname")
    
    port = parsed.port
    if port is not None:
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            netloc = hostname
        else:
            netloc = f"{hostname}:{port}"
    else:
        netloc = hostname
    
    path = parsed.path.rstrip("/") if parsed.path else ""
    
    query = parsed.query
    if query:
        params = sorted(query.split("&"))
        query = "&".join(params)
    
    normalized = urlunparse((scheme, netloc, path, parsed.params, query, ""))
    return normalized


@dataclass
class WebhookSubscription:
    """Represents a webhook subscription."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    url: str = ""
    normalized_url: str = ""
    events: List[str] = field(default_factory=list)
    enabled: bool = True
    workspace_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class WebhookSubscriptionManager:
    """Manages webhook subscriptions with URL normalization and duplicate detection."""
    
    def __init__(self):
        self._subscriptions: Dict[str, WebhookSubscription] = {}
        self._url_index: Dict[str, str] = {}
    
    def create_subscription(
        self,
        url: str,
        events: List[str],
        workspace_id: str = "",
        metadata: Optional[Dict] = None,
    ) -> WebhookSubscription:
        """Create a new webhook subscription with URL normalization.
        
        Raises:
            ValueError: If URL is invalid or a subscription with the same
                       normalized URL already exists in this workspace.
        """
        if not url:
            raise ValueError("URL is required")
        
        if not events:
            raise ValueError("At least one event type is required")
        
        normalized_url = normalize_webhook_url(url)
        
        index_key = f"{workspace_id}:{normalized_url}"
        if index_key in self._url_index:
            existing_id = self._url_index[index_key]
            existing = self._subscriptions.get(existing_id)
            if existing and existing.enabled:
                raise ValueError(
                    f"A subscription with URL '{normalized_url}' already exists "
                    f"in workspace '{workspace_id}'"
                )
        
        sub = WebhookSubscription(
            url=url,
            normalized_url=normalized_url,
            events=events,
            workspace_id=workspace_id,
            metadata=metadata or {},
        )
        
        self._subscriptions[sub.id] = sub
        self._url_index[index_key] = sub.id
        
        return sub
    
    def get_subscription(self, subscription_id: str) -> Optional[WebhookSubscription]:
        return self._subscriptions.get(subscription_id)
    
    def list_subscriptions(self, workspace_id: str = "") -> List[WebhookSubscription]:
        if workspace_id:
            return [s for s in self._subscriptions.values() if s.workspace_id == workspace_id]
        return list(self._subscriptions.values())
    
    def disable_subscription(self, subscription_id: str) -> bool:
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            return False
        sub.enabled = False
        sub.updated_at = time.time()
        return True
    
    def enable_subscription(self, subscription_id: str) -> bool:
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            return False
        sub.enabled = True
        sub.updated_at = time.time()
        return True
    
    def update_events(self, subscription_id: str, events: List[str]) -> bool:
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            return False
        sub.events = events
        sub.updated_at = time.time()
        return True
    
    def delete_subscription(self, subscription_id: str) -> bool:
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            return False
        index_key = f"{sub.workspace_id}:{sub.normalized_url}"
        self._url_index.pop(index_key, None)
        self._subscriptions.pop(subscription_id, None)
        return True
    
    def count(self) -> int:
        return len(self._subscriptions)
