import time
import pytest
from src.agent.executor import AgentExecutor


@pytest.mark.asyncio
async def test_executor_default_config():
    executor = AgentExecutor()
    assert executor.max_results == 1000
    assert executor.result_ttl == 3600.0


@pytest.mark.asyncio
async def test_executor_custom_limits():
    executor = AgentExecutor(max_concurrent=3, max_results=50, result_ttl=60.0)
    assert executor.max_concurrent == 3
    assert executor.max_results == 50
    assert executor.result_ttl == 60.0


@pytest.mark.asyncio
async def test_executor_enforces_max_results():
    """When results exceed max_results, oldest entries are pruned."""
    executor = AgentExecutor(max_concurrent=10, max_results=3, result_ttl=9999)

    async def dummy_handler(aid, task):
        return {"status": "ok", "task": task}

    exec_ids = []
    for i in range(5):
        eid = await executor.execute(f"agent-{i}", {"id": i}, dummy_handler)
        exec_ids.append(eid)

    # After 5 tasks with max_results=3, only 3 should remain
    assert executor.result_count() <= 3
    # The oldest 2 results should have been evicted
    assert executor.get_result(exec_ids[0]) is None
    assert executor.get_result(exec_ids[1]) is None
    # The newest 3 should still be available
    assert executor.get_result(exec_ids[2]) is not None
    assert executor.get_result(exec_ids[3]) is not None
    assert executor.get_result(exec_ids[4]) is not None


@pytest.mark.asyncio
async def test_executor_ttl_eviction():
    """Results older than result_ttl are evicted on next execute."""
    executor = AgentExecutor(max_concurrent=10, max_results=100, result_ttl=0.01)

    async def dummy_handler(aid, task):
        return {"status": "ok"}

    eid1 = await executor.execute("agent-1", {"id": 1}, dummy_handler)
    assert executor.get_result(eid1) is not None

    # Wait for TTL to expire
    time.sleep(0.02)

    # Trigger cleanup by adding another result
    eid2 = await executor.execute("agent-2", {"id": 2}, dummy_handler)

    # The first result should be evicted by TTL
    assert executor.get_result(eid1) is None, "Expired TTL result should be evicted"
    assert executor.get_result(eid2) is not None


@pytest.mark.asyncio
async def test_executor_handles_errors():
    """Errors are stored in results."""
    executor = AgentExecutor(max_concurrent=5)

    async def failing_handler(aid, task):
        raise ValueError("simulated failure")

    eid = await executor.execute("agent-1", {"id": 1}, failing_handler)
    result = executor.get_result(eid)
    assert result is not None
    assert "error" in result
    assert "simulated failure" in result["error"]


@pytest.mark.asyncio
async def test_executor_result_count():
    executor = AgentExecutor(max_concurrent=10, max_results=10)
    assert executor.result_count() == 0

    async def dummy_handler(aid, task):
        return {"ok": True}

    eid = await executor.execute("agent-1", {"id": 1}, dummy_handler)
    assert executor.result_count() == 1
