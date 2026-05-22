"""Tests for AgentExecutor.""" 

import pytest
from src.agent.executor import AgentExecutor


class TestAgentExecutorInit:
    def test_default_max_concurrent(self):
        executor = AgentExecutor()
        assert executor.max_concurrent == 5

    def test_custom_max_concurrent(self):
        executor = AgentExecutor(max_concurrent=10)
        assert executor.max_concurrent == 10

    def test_rejects_zero(self):
        with pytest.raises(ValueError, match="positive integer"):
            AgentExecutor(max_concurrent=0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="positive integer"):
            AgentExecutor(max_concurrent=-1)

    def test_rejects_non_int(self):
        with pytest.raises(ValueError, match="positive integer"):
            AgentExecutor(max_concurrent="5")

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="positive integer"):
            AgentExecutor(max_concurrent=None)

# 2026-05-22T05:10:00 update
