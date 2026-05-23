"""Tests for Agent Sandbox disk quota enforcement."""

import os
import pytest
from src.agent.sandbox import AgentSandbox, ResourceLimits


class TestAgentSandbox:
    def setup_method(self):
        self.sandbox = AgentSandbox()
        self.agent_id = "test-agent"

    def teardown_method(self):
        self.sandbox.destroy(self.agent_id)

    def test_create_sandbox(self):
        path = self.sandbox.create(self.agent_id)
        assert path.exists()
        assert path.name == self.agent_id

    def test_destroy_sandbox(self):
        self.sandbox.create(self.agent_id)
        assert self.sandbox.destroy(self.agent_id) is True
        assert self.sandbox.destroy(self.agent_id) is False

    def test_get_path(self):
        self.sandbox.create(self.agent_id)
        path = self.sandbox.get_path(self.agent_id)
        assert path is not None
        assert path.exists()

    def test_get_path_nonexistent(self):
        assert self.sandbox.get_path("nonexistent") is None

    def test_apply_limits_default(self):
        """apply_limits should not raise with default limits."""
        self.sandbox.create(self.agent_id)
        limits = ResourceLimits()
        # Should not raise
        self.sandbox.apply_limits(self.agent_id, limits)

    def test_disk_usage_empty(self):
        self.sandbox.create(self.agent_id)
        usage = self.sandbox.get_disk_usage(self.agent_id)
        assert usage == 0

    def test_disk_usage_with_file(self):
        self.sandbox.create(self.agent_id)
        path = self.sandbox.get_path(self.agent_id)
        test_file = path / "test.txt"
        test_file.write_text("hello world")
        usage = self.sandbox.get_disk_usage(self.agent_id)
        assert usage > 0
        assert usage == len("hello world")

    def test_is_disk_over_quota(self):
        self.sandbox.create(self.agent_id)
        path = self.sandbox.get_path(self.agent_id)
        # Write a small file
        test_file = path / "data.txt"
        test_file.write_text("x" * 100)
        limits = ResourceLimits(disk_mb=1)  # 1 MB quota
        assert self.sandbox.is_disk_over_quota(self.agent_id, limits) is False

    def test_is_disk_over_quota_exceeded(self):
        self.sandbox.create(self.agent_id)
        path = self.sandbox.get_path(self.agent_id)
        # Write a file larger than quota
        test_file = path / "bigfile.txt"
        test_file.write_text("x" * 10000)
        limits = ResourceLimits(disk_mb=0)  # 0 MB quota
        assert self.sandbox.is_disk_over_quota(self.agent_id, limits) is True

    def test_cleanup_all(self):
        self.sandbox.create("agent-1", ResourceLimits())
        self.sandbox.create("agent-2", ResourceLimits())
        self.sandbox.cleanup_all()
        assert self.sandbox.get_path("agent-1") is None
        assert self.sandbox.get_path("agent-2") is None

    def test_get_path_after_destroy(self):
        self.sandbox.create(self.agent_id)
        self.sandbox.destroy(self.agent_id)
        assert self.sandbox.get_path(self.agent_id) is None

# 2026-05-23T23:36:18 update
