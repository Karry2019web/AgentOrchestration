"""Tests for AgentSandbox path sanitization."""
import os
import tempfile
import pytest
from pathlib import Path
from src.agent.sandbox import AgentSandbox


class TestAgentSandboxSanitization:
    """Regression tests for agent_id sanitization in AgentSandbox.create."""

    @pytest.fixture
    def sandbox(self):
        base = tempfile.mkdtemp(prefix="test_sandbox_")
        sb = AgentSandbox(base_path=base)
        yield sb
        sb.cleanup_all()

    def test_valid_agent_id_accepted(self, sandbox):
        """Normal agent IDs should be accepted."""
        path = sandbox.create("agent-123")
        assert path.exists()
        assert path.is_dir()

    def test_valid_simple_id(self, sandbox):
        """Simple alphanumeric IDs work."""
        path = sandbox.create("my_agent_v2")
        assert path.exists()

    def test_rejects_path_separator_slash(self, sandbox):
        """Forward slash in agent_id should be rejected."""
        with pytest.raises(ValueError, match="path separators"):
            sandbox.create("agent/../etc")

    def test_rejects_path_separator_backslash(self, sandbox):
        """Backslash in agent_id should be rejected."""
        with pytest.raises(ValueError, match="path separators"):
            sandbox.create("agent\\..\\etc")

    def test_rejects_parent_directory_dotdot(self, sandbox):
        """Double-dot parent directory segments should be rejected."""
        with pytest.raises(ValueError, match="parent-directory"):
            sandbox.create("..")

    def test_rejects_dotdot_in_middle(self, sandbox):
        """Double-dot in the middle of agent_id should be rejected."""
        with pytest.raises(ValueError, match="parent-directory"):
            sandbox.create("valid/../../etc")

    def test_rejects_null_byte(self, sandbox):
        """Null byte in agent_id should be rejected."""
        with pytest.raises(ValueError, match="null bytes"):
            sandbox.create("agent\\x00malicious")

    def test_rejects_empty_string(self, sandbox):
        """Empty string agent_id should be rejected."""
        with pytest.raises(ValueError, match="non-empty"):
            sandbox.create("")

    def test_path_stays_under_base(self, sandbox):
        """Resolved sandbox path should remain under base_path."""
        path = sandbox.create("test-agent")
        base_resolved = sandbox.base_path.resolve()
        try:
            path.relative_to(base_resolved)
        except ValueError:
            pytest.fail("Sandbox path is outside base path")

    def test_multiple_sandboxes_isolated(self, sandbox):
        """Multiple sandbox directories should be under base_path."""
        p1 = sandbox.create("agent-alpha")
        p2 = sandbox.create("agent-beta")
        base_resolved = sandbox.base_path.resolve()
        assert str(p1).startswith(str(base_resolved))
        assert str(p2).startswith(str(base_resolved))
        assert p1 != p2
