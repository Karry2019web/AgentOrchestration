"""Tests for AgentExecutor — execution_id returned immediately after scheduling."""

import asyncio
import pytest
from src.agent.executor import AgentExecutor


async def dummy_handler_slow(agent_id: str, task: dict) -> dict:
    """Simulate a long-running task."""
    await asyncio.sleep(1)
    return {"processed": True, "agent_id": agent_id}


async def dummy_handler_fast(agent_id: str, task: dict) -> dict:
    """Simulate a fast task."""
    return {"processed": True, "agent_id": agent_id, "task_id": task.get("id")}


class TestAgentExecutor:
    @pytest.mark.asyncio
    async def test_execute_returns_id_immediately(self):
        """execute() must return execution_id before the handler completes."""
        executor = AgentExecutor(max_concurrent=5)
        task = {"id": "test-task-1", "type": "process"}
        
        start = asyncio.get_event_loop().time()
        execution_id = await executor.execute("agent-1", task, dummy_handler_slow)
        elapsed = asyncio.get_event_loop().time() - start
        
        # execution_id should be returned well before the 1-second handler finishes
        assert elapsed < 0.5, f"execute() took {elapsed:.2f}s — should return id immediately"
        assert execution_id is not None
        assert isinstance(execution_id, str)
        assert len(execution_id) > 0
        
        # The task should still be active (not completed yet)
        assert execution_id in executor._active_tasks
        assert not executor._active_tasks[execution_id].done()
        
        # Wait for completion and verify result
        await asyncio.sleep(1.5)
        result = executor.get_result(execution_id)
        assert result is not None
        assert result["execution_id"] == execution_id
        assert result["result"]["processed"] is True

    @pytest.mark.asyncio
    async def test_cancel_active_execution(self):
        """cancel() should work on an actively running execution."""
        executor = AgentExecutor(max_concurrent=5)
        task = {"id": "test-task-2", "type": "process"}
        
        execution_id = await executor.execute("agent-1", task, dummy_handler_slow)
        assert execution_id in executor._active_tasks
        
        # Cancel the still-running task
        cancelled = executor.cancel(execution_id)
        assert cancelled, "Should successfully cancel a running task"
        
        await asyncio.sleep(0.5)
        assert execution_id not in executor._active_tasks

    @pytest.mark.asyncio
    async def test_shutdown_cancels_all(self):
        """shutdown() should cancel all active tasks."""
        executor = AgentExecutor(max_concurrent=5)
        task = {"id": "test-task-3", "type": "process"}
        
        eid1 = await executor.execute("agent-1", task, dummy_handler_slow)
        eid2 = await executor.execute("agent-2", task, dummy_handler_slow)
        
        await executor.shutdown()
        assert len(executor._active_tasks) == 0

    @pytest.mark.asyncio
    async def test_execution_id_is_unique(self):
        """Each execute() call should return a unique execution_id."""
        executor = AgentExecutor(max_concurrent=5)
        task = {"id": "test-task", "type": "process"}
        
        eid1 = await executor.execute("agent-1", task, dummy_handler_fast)
        eid2 = await executor.execute("agent-2", task, dummy_handler_fast)
        eid3 = await executor.execute("agent-3", task, dummy_handler_fast)
        
        ids = {eid1, eid2, eid3}
        assert len(ids) == 3, "Execution IDs must be unique"
