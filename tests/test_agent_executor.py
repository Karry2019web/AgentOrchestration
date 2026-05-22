"""Tests for the AgentExecutor class."""

import pytest
from src.agent.executor import AgentExecutor


class TestAgentExecutor:
    def test_default_max_concurrent(self):
        executor = AgentExecutor()
        assert executor.max_concurrent == 5

    def test_custom_max_concurrent(self):
        executor = AgentExecutor(max_concurrent=10)
        assert executor.max_concurrent == 10

    def test_negative_max_concurrent_raises(self):
        with pytest.raises(ValueError, match="max_concurrent must be a positive integer"):
            AgentExecutor(max_concurrent=-1)

    def test_zero_max_concurrent_raises(self):
        with pytest.raises(ValueError, match="max_concurrent must be a positive integer"):
            AgentExecutor(max_concurrent=0)

    def test_max_concurrent_one_is_valid(self):
        executor = AgentExecutor(max_concurrent=1)
        assert executor.max_concurrent == 1
