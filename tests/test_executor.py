"""Tests for AgentExecutor result bounding — issue #2119."""

import time
import sys

# Direct import to avoid sandbox's resource module (Unix-only)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "executor",
    "/c/Users/Administrator/AgentOrchestration/src/agent/executor.py"
)
executor_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor_mod)
AgentExecutor = executor_mod.AgentExecutor


class TestAgentExecutorResultsBound:
    def test_results_bounded_by_max_results(self):
        """Given max_results=N, executor keeps at most N completed results."""
        async def dummy_handler(agent_id, task):
            return {"done": True}

        import asyncio
        executor = AgentExecutor(max_concurrent=10, max_results=3, result_ttl=9999)
        ids = []
        for i in range(5):
            exec_id = asyncio.run(executor.execute("agent-a", {"id": f"task-{i}"}, dummy_handler))
            ids.append(exec_id)

        assert len(executor._results) <= 3, (
            f"Expected ≤3 results, got {len(executor._results)}"
        )
        # The first 2 entries should have been evicted
        for eid in ids[:2]:
            assert executor.get_result(eid) is None, (
                f"Old result {eid} should have been evicted"
            )

    def test_recent_results_preserved(self):
        """Recent results under max_results are kept until new pushes them out."""
        async def dummy_handler(agent_id, task):
            return {"done": True}

        import asyncio
        executor = AgentExecutor(max_concurrent=10, max_results=5, result_ttl=9999)
        ids = []
        for i in range(5):
            exec_id = asyncio.run(executor.execute("agent-a", {"id": f"task-{i}"}, dummy_handler))
            ids.append(exec_id)

        # All 5 should still be accessible
        for eid in ids:
            assert executor.get_result(eid) is not None

        # A 6th execution evicts the oldest (id[0])
        new_id = asyncio.run(executor.execute("agent-a", {"id": "task-5"}, dummy_handler))
        assert executor.get_result(ids[0]) is None, "Oldest result should be evicted"
        assert executor.get_result(new_id) is not None, "Newest result should exist"

    def test_default_params(self):
        """Default constructor uses sensible bounds."""
        executor = AgentExecutor()
        assert executor.max_results == 1000
        assert executor.result_ttl == 3600.0
        assert executor.max_concurrent == 5

    def test_cleanup_by_ttl(self):
        """Given result_ttl, stale results older than TTL are evicted."""
        async def dummy_handler(agent_id, task):
            return {"done": True}

        import asyncio
        executor = AgentExecutor(max_concurrent=10, max_results=100, result_ttl=0.01)

        # Execute two tasks to have at least one result
        exec_id = asyncio.run(
            executor.execute("agent-a", {"id": "task-1"}, dummy_handler)
        )

        assert executor.get_result(exec_id) is not None

        # Wait past TTL and trigger cleanup via another execution
        time.sleep(0.02)
        asyncio.run(executor.execute("agent-a", {"id": "task-2"}, dummy_handler))

        # Old result should be evicted
        assert executor.get_result(exec_id) is None, (
            "TTL-expired result should have been evicted"
        )
