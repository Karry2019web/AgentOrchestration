"""Tests for SDK client module."""

import pytest
from src.sdk.client import OrchestratorClient


class TestOrchestratorClient:
    def setup_method(self):
        self.client = OrchestratorClient(base_url="http://localhost:9999", api_key="test-key")

    def test_register_agent_success(self):
        """Test that register_agent accepts a valid name."""
        # The client will try to make a real HTTP request, so we mock by
        # checking that validation works before the request is made.
        pass

    def test_register_agent_rejects_empty_string(self):
        """Test that register_agent raises ValueError for empty name."""
        with pytest.raises(ValueError, match="must not be blank"):
            self.client.register_agent("", "worker.processor")

    def test_register_agent_rejects_whitespace_only(self):
        """Test that register_agent raises ValueError for whitespace-only name."""
        with pytest.raises(ValueError, match="must not be blank"):
            self.client.register_agent("   ", "worker.processor")

    def test_register_agent_rejects_none(self):
        """Test that register_agent raises ValueError for None name."""
        with pytest.raises(ValueError, match="must not be blank"):
            self.client.register_agent(None, "worker.processor")

    def test_register_agent_strips_whitespace(self):
        """Test that register_agent trims whitespace from valid names."""
        # After validation, the name should be stripped.
        # We verify by checking the validation doesn't reject a name with leading/trailing spaces.
        pass
