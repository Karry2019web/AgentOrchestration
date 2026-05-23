"""Tests for AgentSandbox path verification."""

import tempfile
import shutil
from pathlib import Path
from src.agent.sandbox import AgentSandbox


class TestSandboxPathVerification:
    def setup_method(self):
        self.sandbox = AgentSandbox(base_path=tempfile.mkdtemp(prefix="ao_test_"))

    def teardown_method(self):
        self.sandbox.cleanup_all()

    def test_get_path_returns_path_for_active_sandbox(self):
        agent_id = "test-agent-1"
        created = self.sandbox.create(agent_id)
        retrieved = self.sandbox.get_path(agent_id)
        assert retrieved is not None
        assert retrieved == created

    def test_get_path_returns_none_for_unknown_agent(self):
        assert self.sandbox.get_path("nonexistent") is None

    def test_get_path_returns_none_for_externally_removed_sandbox(self):
        agent_id = "test-agent-3"
        sandbox_path = self.sandbox.create(agent_id)
        shutil.rmtree(sandbox_path)
        assert self.sandbox.get_path(agent_id) is None

    def test_get_path_verifies_containment_within_base_path(self):
        agent_id = "test-agent-4"
        self.sandbox.create(agent_id)
        self.sandbox._sandboxes[agent_id] = Path("/tmp/malicious-path")
        assert self.sandbox.get_path(agent_id) is None
