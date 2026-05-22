"""Tests for webhook endpoint validation."""

import pytest
from src.webhook.validator import (
    is_localhost,
    validate_endpoint,
    configure_webhook,
    WebhookConfig,
    WebhookEndpoint,
)


class TestLocalhostDetection:
    def test_detect_localhost_hostname(self):
        assert is_localhost("http://localhost:8080/webhook")
        assert is_localhost("https://localhost/api/callback")
        assert is_localhost("http://localhost")

    def test_detect_loopback_ipv4(self):
        assert is_localhost("http://127.0.0.1:5000/hook")
        assert is_localhost("http://127.0.0.1")
        assert is_localhost("http://127.0.0.2:3000")

    def test_detect_loopback_ipv6(self):
        assert is_localhost("http://[::1]:8080/hook")
        assert is_localhost("http://0.0.0.0:9000")

    def test_reject_external_urls(self):
        assert not is_localhost("https://example.com/webhook")
        assert not is_localhost("https://api.github.com/hooks")
        assert not is_localhost("http://192.168.1.1:8080")

    def test_empty_or_invalid_urls(self):
        assert not is_localhost("")
        assert not is_localhost("not-a-url")


class TestEndpointValidation:
    def test_valid_external_endpoint(self):
        result = validate_endpoint("https://example.com/webhook")
        assert result.allowed
        assert result.error is None

    def test_reject_localhost_by_default(self):
        result = validate_endpoint("http://localhost:8080/hook")
        assert not result.allowed
        assert result.error is not None
        assert "Localhost" in result.error

    def test_reject_loopback_by_default(self):
        result = validate_endpoint("http://127.0.0.1:5000/callback")
        assert not result.allowed
        assert result.error is not None

    def test_allow_localhost_when_configured(self):
        config = WebhookConfig(allow_localhost=True)
        result = validate_endpoint("http://localhost:8080/hook", config)
        assert result.allowed

    def test_allow_specific_localhost_target(self):
        config = WebhookConfig(allowed_localhost_targets={"localhost"})
        result = validate_endpoint("http://localhost:8080/hook", config)
        assert result.allowed

    def test_reject_unallowed_localhost_target(self):
        config = WebhookConfig(allowed_localhost_targets={"127.0.0.1"})
        result = validate_endpoint("http://localhost:8080/hook", config)
        assert not result.allowed

    def test_empty_url(self):
        result = validate_endpoint("")
        assert not result.allowed
        assert result.error is not None

    def test_missing_scheme(self):
        result = validate_endpoint("example.com/webhook")
        assert not result.allowed
        assert "scheme" in result.error.lower()

    def test_unsupported_scheme(self):
        result = validate_endpoint("ftp://example.com/webhook")
        assert not result.allowed
        assert "scheme" in result.error.lower()

    def test_valid_https_endpoint(self):
        result = validate_endpoint("https://api.example.com/v1/webhook")
        assert result.allowed
        assert result.error is None


class TestConfigureWebhook:
    def test_global_config(self):
        configure_webhook(allow_localhost=True)
        result = validate_endpoint("http://localhost:9999/hook")
        assert result.allowed

    def test_global_config_with_targets(self):
        configure_webhook(allowed_localhost_targets={"127.0.0.1"})
        result = validate_endpoint("http://127.0.0.1:8080/hook")
        assert result.allowed
        result2 = validate_endpoint("http://localhost:8080/hook")
        assert not result2.allowed


class TestDeliveryAndRetry:
    """Tests covering valid delivery, rejected delivery, and retry behavior."""

    def test_valid_delivery_to_external(self):
        config = WebhookConfig()
        result = validate_endpoint("https://hooks.example.com/events", config)
        assert result.allowed

    def test_rejected_delivery_to_localhost(self):
        config = WebhookConfig()
        result = validate_endpoint("http://localhost:8000/events", config)
        assert not result.allowed

    def test_workspace_isolation(self):
        """Different workspaces should independently allow/disallow localhost."""
        workspace_a = WebhookConfig(allow_localhost=True)
        workspace_b = WebhookConfig(allow_localhost=False)

        result_a = validate_endpoint("http://localhost:8080/hook", workspace_a)
        result_b = validate_endpoint("http://localhost:8080/hook", workspace_b)

        assert result_a.allowed
        assert not result_b.allowed
