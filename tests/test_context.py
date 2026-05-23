"""Tests for execution context isolation and restoration."""

import pytest
import contextvars
import asyncio
from src.common.context import (
    ContextScope,
    run_with_isolated_context,
    snapshot,
    restore,
    request_id,
    auth_token,
    execution_id,
)


class TestContextScope:
    def test_snapshot_and_restore_roundtrip(self):
        request_id.set("req-001")
        auth_token.set("tok-abc")
        execution_id.set("exec-999")

        saved = snapshot()

        request_id.set("req-002")
        auth_token.set("tok-xyz")

        restore(saved)

        assert request_id.get() == "req-001"
        assert auth_token.get() == "tok-abc"
        assert execution_id.get() == "exec-999"

    def test_context_scope_restores_on_exit(self):
        request_id.set("outer-req")
        auth_token.set("outer-tok")

        with ContextScope():
            request_id.set("inner-req")
            auth_token.set("inner-tok")
            assert request_id.get() == "inner-req"

        assert request_id.get() == "outer-req"
        assert auth_token.get() == "outer-tok"

    def test_context_scope_restores_on_exception(self):
        request_id.set("before-crash")

        class _TestError(Exception):
            pass

        with pytest.raises(_TestError):
            with ContextScope():
                request_id.set("crashed")
                raise _TestError()

        assert request_id.get() == "before-crash"

    def test_run_with_isolated_context_restores_after_await(self):
        """Verify run_with_isolated_context restores outer values even when the
        inner coroutine mutates contextvars."""
        request_id.set("outer-val")

        async def inner():
            request_id.set("inner-val")
            return "done"

        result = asyncio.run(run_with_isolated_context(inner()))
        assert result == "done"
        assert request_id.get() == "outer-val"

    def test_run_with_isolated_context_on_cancellation(self):
        """If the inner coroutine is cancelled the outer context is still restored."""
        outer_val = "persist"

        request_id.set(outer_val)

        async def never_finish():
            request_id.set("stuck")
            await asyncio.Event().wait()

        async def runner():
            task = asyncio.create_task(run_with_isolated_context(never_finish()))
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(runner())
        assert request_id.get() == outer_val


class TestExecutorContextIsolation:
    """Integration-style tests that verify AgentExecutor isolates context per
    execution."""

    @pytest.mark.asyncio
    async def test_executor_isolates_context_per_task(self):
        from src.agent.executor import AgentExecutor

        executor = AgentExecutor(max_concurrent=4)

        async def handler_alpha(agent_id, task):
            request_id.set("alpha-ctx")
            await asyncio.sleep(0.02)
            return request_id.get()

        async def handler_beta(agent_id, task):
            request_id.set("beta-ctx")
            await asyncio.sleep(0.02)
            return request_id.get()

        eid_a = await executor.execute("a", {"id": "t1"}, handler_alpha)
        eid_b = await executor.execute("b", {"id": "t2"}, handler_beta)

        await asyncio.sleep(0.05)

        res_a = executor.get_result(eid_a)
        res_b = executor.get_result(eid_b)

        assert res_a["result"] == "alpha-ctx"
        assert res_b["result"] == "beta-ctx"

    @pytest.mark.asyncio
    async def test_nested_execution_does_not_leak_context(self):
        """A nested call inside a handler must not leak inner contextvars back
        to the outer handler."""
        from src.agent.executor import AgentExecutor

        executor = AgentExecutor(max_concurrent=4)

        async def nested_handler(agent_id, task):
            request_id.set("nested-val")
            return "nested-ok"

        async def outer_handler(agent_id, task):
            request_id.set("outer-val")
            # Simulate a nested agent call
            nested_eid = await executor.execute("inner", {"id": "nested"}, nested_handler)
            executor.get_result(nested_eid)
            return {"outer_ctx": request_id.get()}

        eid = await executor.execute("outer", {"id": "t1"}, outer_handler)
        await asyncio.sleep(0.05)

        result = executor.get_result(eid)
        assert result["result"]["outer_ctx"] == "outer-val"

# 2026-05-23T07:00:00 update

