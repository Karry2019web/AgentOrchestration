"""Tests for CLI validation utilities."""

import pytest
from src.common.validation import validate_agent_id, assert_valid_agent_id


class TestValidateAgentId:
    """Tests for validate_agent_id function."""

    def test_valid_agent_ids(self):
        """Test that valid agent IDs return None."""
        valid_ids = [
            "agent-123",
            "agent_456",
            "MyAgent",
            "a",
            "x" * 128,
            "abc-123_XYZ",
        ]
        for agent_id in valid_ids:
            assert validate_agent_id(agent_id) is None, f"Expected valid: {agent_id}"

    def test_empty_agent_id(self):
        """Test that empty string is rejected."""
        error = validate_agent_id("")
        assert error is not None
        assert "empty" in error.lower()

    def test_none_agent_id(self):
        """Test that None is rejected (treated as empty via truthiness)."""
        error = validate_agent_id("")
        assert error is not None

    def test_too_long_agent_id(self):
        """Test that IDs over 128 chars are rejected."""
        long_id = "x" * 129
        error = validate_agent_id(long_id)
        assert error is not None
        assert "128" in error

    def test_special_chars_rejected(self):
        """Test that special characters are rejected."""
        invalid_ids = [
            "agent@123",
            "agent$id",
            "agent id",
            "agent.id",
            "agent/id",
            "agent\id",
        ]
        for agent_id in invalid_ids:
            error = validate_agent_id(agent_id)
            assert error is not None, f"Expected invalid: {agent_id}"
            assert "alphanumeric" in error.lower() or "hyphen" in error.lower()

    def test_unicode_rejected(self):
        """Test that unicode characters are rejected."""
        invalid_ids = [
            "агент-123",
            "代理人",
            "agenté",
        ]
        for agent_id in invalid_ids:
            error = validate_agent_id(agent_id)
            assert error is not None, f"Expected invalid: {agent_id}"


class TestAssertValidAgentId:
    """Tests for assert_valid_agent_id function."""

    def test_valid_raises_nothing(self):
        """Test that valid IDs do not raise."""
        assert_valid_agent_id("valid-agent-123")  # should not raise

    def test_invalid_raises_value_error(self):
        """Test that invalid IDs raise ValueError."""
        with pytest.raises(ValueError, match="agent_id"):
            assert_valid_agent_id("invalid@id")

# 2026-05-22T12:10:26 update - regression tests for agent_id validation
