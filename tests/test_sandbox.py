"""Tests for Agent Sandbox — ResourceLimits enforcement."""

import os
import resource
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent.sandbox import AgentSandbox, ResourceLimits


class TestResourceLimits:
    """ResourceLimits data class creation."""

    def test_default_limits(self):
        limits = ResourceLimits()
        assert limits.cpu_time == 60
        assert limits.memory_mb == 512
        assert limits.disk_mb == 100

    def test_custom_limits(self):
        limits = ResourceLimits(cpu_time=30, memory_mb=256, disk_mb=50)
        assert limits.cpu_time == 30
        assert limits.memory_mb == 256
        assert limits.disk_mb == 50

    def test_zero_disk_mb(self):
        limits = ResourceLimits(disk_mb=0)
        assert limits.disk_mb == 0


class TestAgentSandbox:
    """AgentSandbox lifecycle and limit enforcement."""

    def test_create_and_destroy(self):
        sandbox = AgentSandbox()
        agent_id = "test-agent"
        path = sandbox.create(agent_id)
        assert path.exists()
        assert path.name == agent_id
        assert sandbox.destroy(agent_id) is True
        assert path.exists() is False

    def test_get_path(self):
        sandbox = AgentSandbox()
        agent_id = "test-agent"
        sandbox.create(agent_id)
        assert sandbox.get_path(agent_id) is not None
        assert sandbox.destroy(agent_id) is True
        assert sandbox.get_path(agent_id) is None

    def test_destroy_nonexistent(self):
        sandbox = AgentSandbox()
        assert sandbox.destroy("nonexistent") is False

    def test_cleanup_all(self):
        sandbox = AgentSandbox()
        sandbox.create("agent-1")
        sandbox.create("agent-2")
        sandbox.cleanup_all()
        assert sandbox.get_path("agent-1") is None
        assert sandbox.get_path("agent-2") is None

    @patch("resource.setrlimit")
    def test_apply_limits_enforces_disk_mb(self, mock_setrlimit):
        """apply_limits must enforce disk_mb via RLIMIT_FSIZE."""
        sandbox = AgentSandbox()
        sandbox.create("test-agent")
        limits = ResourceLimits(cpu_time=10, memory_mb=128, disk_mb=50)

        with patch.object(sandbox, "apply_limits", wraps=sandbox.apply_limits) as spy:
            sandbox.apply_limits("test-agent", limits)

        expected_disk_bytes = 50 * 1024 * 1024
        mock_setrlimit.assert_any_call(
            resource.RLIMIT_FSIZE, (expected_disk_bytes, expected_disk_bytes)
        )

    @patch("resource.setrlimit")
    def test_apply_limits_with_create(self, mock_setrlimit):
        """When limits are passed to create(), apply_limits is called."""
        sandbox = AgentSandbox()
        limits = ResourceLimits(cpu_time=30, memory_mb=256, disk_mb=200)
        sandbox.create("test-agent", limits=limits)

        expected_disk_bytes = 200 * 1024 * 1024
        mock_setrlimit.assert_any_call(
            resource.RLIMIT_FSIZE, (expected_disk_bytes, expected_disk_bytes)
        )
        mock_setrlimit.assert_any_call(resource.RLIMIT_CPU, (30, 30))
        expected_mem = 256 * 1024 * 1024
        mock_setrlimit.assert_any_call(
            resource.RLIMIT_AS, (expected_mem, expected_mem)
        )
