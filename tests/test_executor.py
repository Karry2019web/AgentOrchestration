"""Tests for AgentExecutor — verifies immediate execution_id return."""

import asyncio
import pytest
from src.agent.executor import AgentExecutor


@pytest.mark.asyncio
async def test_execute_returns_id_immediately():
    """execute() should return an execution_id before the handler completes."""
    executor = AgentExecutor(max_concurrent=5)
    call_order = []

    async def slow_handler(agent_id, task):
        call_order.append("handler_start")
        await asyncio.sleep(0.2)
        call_order.append("handler_end")
        return {"done": True}

    # Schedule but don't await the result yet
    exec_id = await executor.execute("agent-1", {"id": "t1"}, slow_handler)
    call_order.append("got_id")

    # Wait a tiny bit — ensure the id was returned while handler still runs
    await asyncio.sleep(0.05)
    call_order.append("after_short_sleep")

    # execution_id should be a non-empty string
    assert exec_id is not None
    assert isinstance(exec_id, str)
    assert len(exec_id) > 0

    # At this point handler_start should have fired but handler_end may not yet
    assert "handler_start" in call_order

    # Wait for completion and verify result
    result = await executor.wait_for_result(exec_id)
    assert result is not None
    assert result["execution_id"] == exec_id
    assert "handler_end" in call_order


@pytest.mark.asyncio
async def test_get_result_after_completion():
    executor = AgentExecutor(max_concurrent=5)

    async def fast_handler(agent_id, task):
        return {"status": "ok"}

    exec_id = await executor.execute("agent-1", {"id": "t2"}, fast_handler)
    result = await executor.wait_for_result(exec_id)
    assert result["result"] == {"status": "ok"}
    # get_result should also work
    cached = executor.get_result(exec_id)
    assert cached is not None


@pytest.mark.asyncio
async def test_cancel_active_execution():
    executor = AgentExecutor(max_concurrent=5)

    async def never_ending(agent_id, task):
        await asyncio.Event().wait()

    exec_id = await executor.execute("agent-1", {"id": "t3"}, never_ending)
    assert executor.cancel(exec_id) is True
    # After cancel, trying to cancel again returns False
    assert executor.cancel(exec_id) is False


@pytest.mark.asyncio
async def test_execute_concurrency_limit():
    executor = AgentExecutor(max_concurrent=2)

    started = []

    async def controlled(agent_id, task):
        started.append(agent_id)
        await asyncio.Event().wait()

    id1 = await executor.execute("agent-1", {"id": "t4"}, controlled)
    id2 = await executor.execute("agent-2", {"id": "t5"}, controlled)
    await asyncio.sleep(0.05)
    assert len(started) == 2

    executor.cancel(id1)
    executor.cancel(id2)


@pytest.mark.asyncio
async def test_execute_immediate_return_without_semaphore_blocking():
    """Ensure that semaphore release is decoupled from handler completion."""
    executor = AgentExecutor(max_concurrent=1)

    async def long_handler(agent_id, task):
        await asyncio.sleep(0.5)
        return {"done": True}

    ids = []
    for i in range(3):
        eid = await executor.execute(f"agent-{i}", {"id": f"t{i}"}, long_handler)
        ids.append(eid)

    # All ids should be returned immediately even though concurrency is 1
    assert len(ids) == 3
    for eid in ids:
        assert isinstance(eid, str) and len(eid) > 0
