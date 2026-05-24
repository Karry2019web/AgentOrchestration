"""Tests for AgentExecutor — memory-bound result storage."""

import asyncio
import time
from src.agent.executor import AgentExecutor


async def dummy_handler(agent_id: str, task: dict) -> str:
    await asyncio.sleep(0.001)
    return f"done-{task.get('id', 'unknown')}"


class TestAgentExecutorBoundedResults:
    """Sandbox: Bound stored executor results — memory management."""

    def test_default_max_results(self):
        executor = AgentExecutor()
        assert executor.max_results == 1000
        assert executor.result_count() == 0

    def test_custom_max_results(self):
        executor = AgentExecutor(max_results=5)
        assert executor.max_results == 5

    def test_custom_ttl(self):
        executor = AgentExecutor(result_ttl=0.1)
        assert executor.result_ttl == 0.1

    def test_results_bounded_by_max_count(self):
        executor = AgentExecutor(max_concurrent=10, max_results=3)

        async def run():
            for i in range(5):
                exec_id = await executor.execute(
                    "agent-1", {"id": f"task-{i}"}, dummy_handler
                )
            assert executor.result_count() <= 3, (
                f"Expected ≤3 results, got {executor.result_count()}"
            )

        asyncio.run(run())

    def test_stale_results_removed_by_ttl(self):
        executor = AgentExecutor(max_concurrent=10, max_results=100, result_ttl=0.05)

        async def run():
            exec_id = await executor.execute(
                "agent-1", {"id": "task-1"}, dummy_handler
            )
            assert executor.get_result(exec_id) is not None
            await asyncio.sleep(0.1)
            executor._enforce_limits()
            assert executor.get_result(exec_id) is None, (
                "Result should have been removed after TTL expiry"
            )

        asyncio.run(run())

    def test_get_result_returns_none_for_missing(self):
        executor = AgentExecutor()
        assert executor.get_result("nonexistent-id") is None

    def test_result_count_after_enforcement(self):
        executor = AgentExecutor(max_concurrent=10, max_results=2)

        async def run():
            for i in range(4):
                await executor.execute("agent-1", {"id": f"task-{i}"}, dummy_handler)
            assert executor.result_count() == 2
            assert executor.get_result("nonexistent") is None

        asyncio.run(run())
