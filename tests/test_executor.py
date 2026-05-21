import pytest
import asyncio
from src.agent.executor import AgentExecutor


class TestAgentExecutor:
    def setup_method(self):
        self.executor = AgentExecutor(max_concurrent=5)

    def test_execute_returns_execution_id(self):
        async def run():
            async def handler(aid, task):
                return {"processed": True}
            exec_id = await self.executor.execute("agent-1", {"id": "t1"}, handler)
            assert exec_id is not None
            result = self.executor.get_result(exec_id)
            assert result is not None
            assert result["execution_id"] == exec_id
            assert result["agent_id"] == "agent-1"
            assert result["task_id"] == "t1"
            assert result["result"]["processed"] is True
        asyncio.run(run())

    def test_cancelled_execution_stores_cancelled_result(self):
        async def run():
            async def never_completes(aid, task):
                await asyncio.Event().wait()  # never resolves
                return {"done": True}

            exec_id = await self.executor.execute("agent-2", {"id": "t2"}, never_completes)
            # Cancel the execution immediately
            assert self.executor.cancel(exec_id) is True
            # Give the event loop a chance to process cancellation
            await asyncio.sleep(0.1)
            result = self.executor.get_result(exec_id)
            assert result is not None
            assert result["execution_id"] == exec_id
            assert result["status"] == "cancelled"
        asyncio.run(run())

    def test_cancel_non_existent_execution(self):
        assert self.executor.cancel("nonexistent-id") is False

    def test_get_result_nonexistent(self):
        assert self.executor.get_result("nonexistent-id") is None

    def test_shutdown_cancels_active_tasks(self):
        async def run():
            async def long_running(aid, task):
                await asyncio.sleep(999)
                return {"done": True}

            exec_id = await self.executor.execute("agent-3", {"id": "t3"}, long_running)
            await self.executor.shutdown()
            result = self.executor.get_result(exec_id)
            assert result is not None
            assert result.get("status") == "cancelled" or "error" in result
        asyncio.run(run())

# 2026-05-22T00:00:00 initial
