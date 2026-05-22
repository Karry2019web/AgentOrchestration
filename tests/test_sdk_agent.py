"""Tests for SDK agent metadata validation."""

import pytest
from src.sdk.agent import BaseAgent


class StubAgent(BaseAgent):
    """Concrete stub for testing the abstract BaseAgent."""

    async def setup(self) -> None:
        pass

    async def handle_task(self, task: dict) -> None:
        return task

    async def cleanup(self) -> None:
        pass


class TestBaseAgentMetadata:
    """Tests for BaseAgent.set_metadata key validation."""

    def setup_method(self):
        self.agent = StubAgent("test-id", "test-agent")

    def test_set_metadata_accepts_non_empty_string_key(self):
        """Valid non-empty string keys should be stored."""
        self.agent.set_metadata("trace_id", "abc-123")
        assert self.agent.get_metadata("trace_id") == "abc-123"

    def test_set_metadata_rejects_empty_string_key(self):
        """Empty string keys should raise ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            self.agent.set_metadata("", "value")

    def test_set_metadata_rejects_whitespace_only_key(self):
        """Whitespace-only keys should raise ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            self.agent.set_metadata("   ", "value")

    def test_set_metadata_rejects_none_key(self):
        """None keys should raise ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            self.agent.set_metadata(None, "value")  # type: ignore

    def test_set_metadata_rejects_non_string_key(self):
        """Non-string keys (int, list) should raise ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            self.agent.set_metadata(123, "value")
        with pytest.raises(ValueError, match="non-empty"):
            self.agent.set_metadata(["key"], "value")

    def test_set_metadata_trims_whitespace(self):
        """Keys with surrounding whitespace should be trimmed before storage."""
        self.agent.set_metadata("  my_key  ", "value")
        assert self.agent.get_metadata("my_key") == "value"
        assert self.agent.get_metadata("  my_key  ") is None

    def test_get_metadata_default(self):
        """Missing keys should return the default value."""
        assert self.agent.get_metadata("nonexistent") is None
        assert self.agent.get_metadata("nonexistent", "default") == "default"
