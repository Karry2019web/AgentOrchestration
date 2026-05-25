"""Tests for the Orchestrator API client SDK."""

from unittest.mock import patch
from src.sdk.client import OrchestratorClient


class TestOrchestratorClient:
    def setup_method(self):
        self.client = OrchestratorClient(
            base_url="https://test.api.io",
            api_key="test-key-123",
        )

    def test_default_timeout(self):
        """Default timeout should be 30 seconds."""
        client = OrchestratorClient(base_url="https://test.api.io", api_key="key")
        assert client.timeout == 30

    def test_custom_timeout(self):
        """Timeout should be configurable via constructor."""
        client = OrchestratorClient(base_url="https://test.api.io", api_key="key", timeout=10)
        assert client.timeout == 10

    def test_timeout_passed_to_urlopen(self):
        """Timeout should be passed to urlopen in _request."""
        client = OrchestratorClient(
            base_url="https://test.api.io",
            api_key="test-key",
            timeout=5,
        )
        with patch("src.sdk.client.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b'{"ok": true}'
            result = client.list_agents()
            _, kwargs = mock_urlopen.call_args
            assert kwargs.get("timeout") == 5

    def test_timeout_zero_disables(self):
        """Timeout=0 should be passable (disables the timeout)."""
        client = OrchestratorClient(base_url="https://test.api.io", api_key="key", timeout=0)
        assert client.timeout == 0
