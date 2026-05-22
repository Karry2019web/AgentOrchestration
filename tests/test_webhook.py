"""Tests for webhook URL normalization and subscription management."""

import pytest
from src.webhook.subscription import normalize_webhook_url, WebhookSubscriptionManager


class TestNormalizeWebhookURL:
    def test_lowercases_scheme(self):
        assert normalize_webhook_url("HTTP://example.com/hook") == "http://example.com/hook"

    def test_lowercases_hostname(self):
        assert normalize_webhook_url("http://Example.COM/Hook") == "http://example.com/Hook"

    def test_removes_default_http_port(self):
        assert normalize_webhook_url("http://example.com:80/hook") == "http://example.com/hook"

    def test_removes_default_https_port(self):
        assert normalize_webhook_url("https://example.com:443/hook") == "https://example.com/hook"

    def test_keeps_non_default_port(self):
        assert normalize_webhook_url("http://example.com:8080/hook") == "http://example.com:8080/hook"

    def test_removes_trailing_slash(self):
        assert normalize_webhook_url("http://example.com/hook/") == "http://example.com/hook"

    def test_removes_fragment(self):
        assert normalize_webhook_url("http://example.com/hook#section") == "http://example.com/hook"

    def test_sorts_query_parameters(self):
        result = normalize_webhook_url("http://example.com/hook?b=2&a=1")
        assert result == "http://example.com/hook?a=1&b=2"

    def test_https_with_non_default_port(self):
        assert normalize_webhook_url("https://example.com:8443/hook") == "https://example.com:8443/hook"

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            normalize_webhook_url("")

    def test_unsupported_scheme_raises(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            normalize_webhook_url("ftp://example.com/hook")

    def test_no_hostname_raises(self):
        with pytest.raises(ValueError, match="must have a hostname"):
            normalize_webhook_url("http:///path")

    def test_handles_root_path(self):
        assert normalize_webhook_url("http://example.com") == "http://example.com"

    def test_handles_root_path_with_slash(self):
        assert normalize_webhook_url("http://example.com/") == "http://example.com"

    def test_preserves_query_without_sort_when_single(self):
        result = normalize_webhook_url("http://example.com/hook?token=abc")
        assert result == "http://example.com/hook?token=abc"

    def test_equivalent_urls_normalize_same(self):
        a = normalize_webhook_url("HTTP://EXAMPLE.COM:80/hook/")
        b = normalize_webhook_url("http://example.com/hook")
        assert a == b

    def test_subdomain_distinction(self):
        a = normalize_webhook_url("http://api.example.com/hook")
        b = normalize_webhook_url("http://example.com/hook")
        assert a != b


class TestWebhookSubscriptionManager:
    def test_create_subscription(self):
        mgr = WebhookSubscriptionManager()
        sub = mgr.create_subscription(
            url="http://example.com/hook",
            events=["task.completed", "agent.started"],
            workspace_id="ws-1",
        )
        assert sub.url == "http://example.com/hook"
        assert sub.normalized_url == "http://example.com/hook"
        assert sub.events == ["task.completed", "agent.started"]
        assert sub.workspace_id == "ws-1"
        assert sub.enabled is True
        assert mgr.count() == 1

    def test_create_subscription_normalizes_url(self):
        mgr = WebhookSubscriptionManager()
        sub = mgr.create_subscription(
            url="HTTP://EXAMPLE.COM:80/HOOK/",
            events=["task.completed"],
        )
        assert sub.normalized_url == "http://example.com/HOOK"

    def test_duplicate_url_in_same_workspace_raises(self):
        mgr = WebhookSubscriptionManager()
        mgr.create_subscription(
            url="http://example.com/hook",
            events=["task.completed"],
            workspace_id="ws-1",
        )
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_subscription(
                url="http://example.com/hook",
                events=["agent.started"],
                workspace_id="ws-1",
            )

    def test_same_url_different_workspace_allowed(self):
        mgr = WebhookSubscriptionManager()
        mgr.create_subscription(url="http://example.com/hook", events=["a"], workspace_id="ws-1")
        mgr.create_subscription(url="http://example.com/hook", events=["b"], workspace_id="ws-2")
        assert mgr.count() == 2

    def test_normalized_duplicate_detected(self):
        mgr = WebhookSubscriptionManager()
        mgr.create_subscription(
            url="HTTP://EXAMPLE.COM:80/HOOK/",
            events=["task.completed"],
            workspace_id="ws-1",
        )
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_subscription(
                url="http://example.com/hook",
                events=["agent.started"],
                workspace_id="ws-1",
            )

    def test_disabled_subscription_allows_recreate(self):
        mgr = WebhookSubscriptionManager()
        sub = mgr.create_subscription(
            url="http://example.com/hook",
            events=["task.completed"],
            workspace_id="ws-1",
        )
        mgr.disable_subscription(sub.id)
        new_sub = mgr.create_subscription(
            url="http://example.com/hook",
            events=["agent.started"],
            workspace_id="ws-1",
        )
        assert new_sub.id != sub.id
        assert mgr.count() == 2  # old disabled + new enabled

    def test_empty_url_raises(self):
        mgr = WebhookSubscriptionManager()
        with pytest.raises(ValueError, match="URL is required"):
            mgr.create_subscription(url="", events=["a"])

    def test_empty_events_raises(self):
        mgr = WebhookSubscriptionManager()
        with pytest.raises(ValueError, match="At least one event type"):
            mgr.create_subscription(url="http://example.com/hook", events=[])

    def test_get_subscription(self):
        mgr = WebhookSubscriptionManager()
        created = mgr.create_subscription(url="http://example.com/hook", events=["a"])
        retrieved = mgr.get_subscription(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id

    def test_get_nonexistent_subscription(self):
        mgr = WebhookSubscriptionManager()
        assert mgr.get_subscription("nonexistent") is None

    def test_list_subscriptions(self):
        mgr = WebhookSubscriptionManager()
        mgr.create_subscription(url="http://a.com/hook", events=["a"], workspace_id="ws-1")
        mgr.create_subscription(url="http://b.com/hook", events=["b"], workspace_id="ws-2")
        mgr.create_subscription(url="http://c.com/hook", events=["c"], workspace_id="ws-1")
        ws1_subs = mgr.list_subscriptions("ws-1")
        assert len(ws1_subs) == 2
        all_subs = mgr.list_subscriptions()
        assert len(all_subs) == 3

    def test_disable_and_enable_subscription(self):
        mgr = WebhookSubscriptionManager()
        sub = mgr.create_subscription(url="http://example.com/hook", events=["a"])
        assert sub.enabled is True
        mgr.disable_subscription(sub.id)
        assert mgr.get_subscription(sub.id).enabled is False
        mgr.enable_subscription(sub.id)
        assert mgr.get_subscription(sub.id).enabled is True

    def test_disable_nonexistent_returns_false(self):
        mgr = WebhookSubscriptionManager()
        assert mgr.disable_subscription("nonexistent") is False

    def test_update_events(self):
        mgr = WebhookSubscriptionManager()
        sub = mgr.create_subscription(url="http://example.com/hook", events=["a"])
        mgr.update_events(sub.id, ["b", "c"])
        assert mgr.get_subscription(sub.id).events == ["b", "c"]

    def test_update_events_nonexistent_returns_false(self):
        mgr = WebhookSubscriptionManager()
        assert mgr.update_events("nonexistent", ["a"]) is False

    def test_delete_subscription(self):
        mgr = WebhookSubscriptionManager()
        sub = mgr.create_subscription(url="http://example.com/hook", events=["a"])
        assert mgr.count() == 1
        mgr.delete_subscription(sub.id)
        assert mgr.count() == 0
        assert mgr.get_subscription(sub.id) is None

    def test_delete_subscription_clears_index(self):
        mgr = WebhookSubscriptionManager()
        sub = mgr.create_subscription(url="http://example.com/hook", events=["a"], workspace_id="ws-1")
        mgr.delete_subscription(sub.id)
        # Should be able to recreate with same URL
        new_sub = mgr.create_subscription(
            url="http://example.com/hook", events=["b"], workspace_id="ws-1"
        )
        assert new_sub is not None
        assert mgr.count() == 1
