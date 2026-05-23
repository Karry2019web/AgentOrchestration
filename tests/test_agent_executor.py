"""Tests for AgentExecutor cancellation behavior."""

import asyncio

import pytest

from src.agent.executor import AgentExecutor


class TestAgentExecutorCancellation:
    """When an execution is cancelled, it must leave a terminal result object."""

    async def _never_completing_handler(self, agent_id, task):
        """Handler that never returns — used to test cancellation."""
        await asyncio.Event().wait()

    async def test_cancel_stores_terminal_result(self):
        """Cancelled executions produce a result with status='cancelled'."""
        executor = AgentExecutor()
        started = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await asyncio.Event().wait()

        execute_task = asyncio.create_task(
            executor.execute("agent-1", {"id": "task-1"}, handler)
        )

        await started.wait()
        # Get the one active execution
        assert len(executor._active_tasks) == 1
        execution_id = next(iter(executor._active_tasks))

        assert executor.cancel(execution_id) is True
        await execute_task

        result = executor.get_result(execution_id)
        assert result is not None
        assert result["execution_id"] == execution_id
        assert result["agent_id"] == "agent-1"
        assert result["task_id"] == "task-1"
        assert result["status"] == "cancelled"
        assert result["error"] == "Execution cancelled"
        assert "timestamp" in result
        # Task should be cleaned up from active set
        assert execution_id not in executor._active_tasks

    async def test_cancel_unknown_id_returns_false(self):
        """Cancelling a non-existent execution returns False."""
        executor = AgentExecutor()
        assert executor.cancel("nonexistent-id") is False

    async def test_cancel_already_completed_returns_false(self):
        """Cancelling a completed execution returns False."""
        executor = AgentExecutor()

        async def quick_handler(agent_id, task):
            return {"done": True}

        exec_id = await executor.execute("agent-1", {"id": "task-1"}, quick_handler)

        # Execution already completed
        result = executor.get_result(exec_id)
        assert result is not None
        assert result["status"] != "cancelled"

        # Cancel should return False since task is already done
        assert executor.cancel(exec_id) is False

    async def test_multiple_concurrent_cancellations(self):
        """Multiple concurrent executions can be cancelled independently."""
        executor = AgentExecutor(max_concurrent=10)
        started_count = 0
        start_barrier = asyncio.Event()

        async def slow_handler(agent_id, task):
            nonlocal started_count
            started_count += 1
            start_barrier.set()
            await asyncio.Event().wait()

        # Start 3 concurrent executions
        exec_ids = []
        tasks = []
        for i in range(3):
            t = asyncio.create_task(
                executor.execute("agent-1", {"id": f"task-{i}"}, slow_handler)
            )
            tasks.append(t)

        await start_barrier.wait()
        await asyncio.sleep(0.1)

        # Cancel 2 of them
        exec_ids = list(executor._active_tasks.keys())
        assert len(exec_ids) == 3

        cancelled_ids = exec_ids[:2]
        remaining_id = exec_ids[2]

        for cid in cancelled_ids:
            assert executor.cancel(cid) is True

        # Wait for cancelled tasks to complete
        for t in tasks[:2]:
            await t

        # Verify cancelled results
        for cid in cancelled_ids:
            result = executor.get_result(cid)
            assert result is not None
            assert result["execution_id"] == cid
            assert result["status"] == "cancelled"

        # The remaining task should still be active
        assert remaining_id in executor._active_tasks

        # Clean up
        executor.cancel(remaining_id)
        await asyncio.gather(tasks[2], return_exceptions=True)

    async def test_shutdown_handles_cancellation_gracefully(self):
        """shutdown() should cancel all active tasks without errors."""
        executor = AgentExecutor(max_concurrent=10)

        async def blocking_handler(agent_id, task):
            await asyncio.Event().wait()

        # Start multiple executions
        tasks = []
        for i in range(5):
            t = asyncio.create_task(
                executor.execute("agent-1", {"id": f"task-{i}"}, blocking_handler)
            )
            tasks.append(t)

        await asyncio.sleep(0.1)
        assert len(executor._active_tasks) == 5

        # Shutdown should cancel everything gracefully
        await executor.shutdown()
        assert len(executor._active_tasks) == 0

        # All executions should have a result (either cancelled or never started)
        # Those that started should have cancelled results
        for t in tasks:
            # They all completed (with CancelledError handled)
            pass


@pytest.mark.asyncio
async def test_cancel_regression_sandbox():
    """Regression: the scenario from the bounty issue.

    A polling client should always get a result after cancellation,
    never None even when the execution timed out externally.
    """
    executor = AgentExecutor()

    async def handler(agent_id, task):
        await asyncio.sleep(1000)

    exec_id = await executor.execute("agent-1", {"id": "reg-task"}, handler)
    await asyncio.sleep(0.05)

    # Simulate external timeout / cancellation
    assert executor.cancel(exec_id) is True

    # Give the cancellation error time to propagate
    await asyncio.sleep(0.1)

    # Polling client must never see None
    result = executor.get_result(exec_id)
    assert result is not None, "Cancelled execution must produce a terminal result"
    assert result["status"] == "cancelled"
    assert "error" in result
