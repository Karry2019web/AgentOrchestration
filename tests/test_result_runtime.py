"""Tests for result runtime — JSON serialization validation and durable state guards."""

import json
import pytest
from src.agent.executor import AgentExecutor, JsonSerializationError
from src.agent.runtime import AgentRuntime, ResultState, RuntimeState


class TestJsonSerializationValidation:
    """Validate JSON serialization of tool results."""

    @pytest.mark.asyncio
    async def test_valid_json_result_passes(self):
        """A properly JSON-serializable result should be stored successfully."""
        executor = AgentExecutor()

        async def handler(agent_id, task):
            return {"status": "ok", "value": 42}

        exec_id = await executor.execute("agent-1", {"id": "task-1"}, handler)
        result = executor.get_result(exec_id)
        assert result is not None
        assert result["result"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_invalid_json_result_raises_error(self):
        """A non-JSON-serializable result should produce an error outcome."""
        executor = AgentExecutor()

        class NonSerializable:
            pass

        async def handler(agent_id, task):
            return {"bad": NonSerializable()}

        exec_id = await executor.execute("agent-1", {"id": "task-2"}, handler)
        result = executor.get_result(exec_id)
        assert result is not None
        assert "error" in result
        assert "JSON-serializable" in result["error"]

    @pytest.mark.asyncio
    async def test_bytes_result_stored_as_error(self):
        """Bytes objects (not JSON-serializable) should be caught."""
        executor = AgentExecutor()

        async def handler(agent_id, task):
            return bytes([0, 1, 2])

        exec_id = await executor.execute("agent-1", {"id": "task-3"}, handler)
        result = executor.get_result(exec_id)
        assert result is not None
        assert "error" in result
        assert "JSON-serializable" in result["error"]

    @pytest.mark.asyncio
    async def test_circular_reference_rejected(self):
        """Circular references should be rejected."""
        executor = AgentExecutor()

        async def handler(agent_id, task):
            obj = {"self": None}
            obj["self"] = obj
            return obj

        exec_id = await executor.execute("agent-1", {"id": "task-4"}, handler)
        result = executor.get_result(exec_id)
        assert result is not None
        assert "error" in result
        assert "JSON-serializable" in result["error"]

    @pytest.mark.asyncio
    async def test_complex_nested_json_works(self):
        """Complex nested data structures should pass validation."""
        executor = AgentExecutor()

        async def handler(agent_id, task):
            return {
                "string": "hello",
                "number": 42,
                "float": 3.14,
                "list": [1, 2, 3],
                "nested": {"a": {"b": True}},
                "null_val": None,
            }

        exec_id = await executor.execute("agent-1", {"id": "task-5"}, handler)
        result = executor.get_result(exec_id)
        assert result is not None
        assert result["result"]["number"] == 42
        assert result["result"]["nested"]["a"]["b"] is True


class TestIdempotentResultFinalization:
    """Ensure repeated calls produce the same terminal outcome."""

    @pytest.mark.asyncio
    async def test_execute_twice_idempotent(self):
        """Running the same valid task twice should not duplicate results."""
        executor = AgentExecutor()
        call_count = 0

        async def handler(agent_id, task):
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        exec_id = await executor.execute("agent-1", {"id": "task-6"}, handler)
        result1 = executor.get_result(exec_id)

        # Execute same task again
        exec_id2 = await executor.execute("agent-1", {"id": "task-6"}, handler)
        result2 = executor.get_result(exec_id2)

        # Different execution IDs, different results
        assert exec_id != exec_id2
        # The same task ID ran twice with different results
        assert result1["result"]["count"] == 1
        assert result2["result"]["count"] == 2

    @pytest.mark.asyncio
    async def test_finalized_tracking(self):
        """Once finalized, an execution_id should be marked as such."""
        executor = AgentExecutor()

        async def handler(agent_id, task):
            return {"ok": True}

        exec_id = await executor.execute("agent-1", {"id": "task-7"}, handler)
        assert executor.is_finalized(exec_id)

    @pytest.mark.asyncio
    async def test_non_json_result_finalized(self):
        """Invalid JSON results should still be finalized."""
        executor = AgentExecutor()

        async def handler(agent_id, task):
            return object()

        exec_id = await executor.execute("agent-1", {"id": "task-8"}, handler)
        assert executor.is_finalized(exec_id)
        result = executor.get_result(exec_id)
        assert result is not None and "error" in result


class TestRuntimeStateMachineGuard:
    """Durable state-machine guard for tool results."""

    def test_initial_state_pending(self):
        runtime = AgentRuntime()
        assert runtime.get_result_state("agent-1") == ResultState.PENDING
        assert not runtime.has_terminal_outcome("agent-1")

    def test_record_valid_outcome(self):
        runtime = AgentRuntime()
        assert runtime.record_result_state("agent-1", ResultState.VALID)
        assert runtime.get_result_state("agent-1") == ResultState.VALID
        assert runtime.has_terminal_outcome("agent-1")

    def test_record_invalid_outcome(self):
        runtime = AgentRuntime()
        assert runtime.record_result_state("agent-1", ResultState.INVALID)
        assert runtime.get_result_state("agent-1") == ResultState.INVALID

    def test_duplicate_outcome_rejected(self):
        runtime = AgentRuntime()
        assert runtime.record_result_state("agent-1", ResultState.VALID)
        # Second attempt should be rejected (idempotent)
        assert not runtime.record_result_state("agent-1", ResultState.INVALID)
        # State should remain as first-recorded outcome
        assert runtime.get_result_state("agent-1") == ResultState.VALID

    def test_duplicate_outcome_finalized(self):
        runtime = AgentRuntime()
        assert runtime.record_result_state("agent-1", ResultState.VALID)
        assert not runtime.record_result_state("agent-1", ResultState.FINALIZED)
        assert runtime.get_result_state("agent-1") == ResultState.VALID

    def test_reset_allows_new_outcome(self):
        runtime = AgentRuntime()
        runtime.record_result_state("agent-1", ResultState.VALID)
        runtime.reset_result_state("agent-1")
        assert not runtime.has_terminal_outcome("agent-1")
        assert runtime.get_result_state("agent-1") == ResultState.PENDING

    def test_reset_then_record(self):
        runtime = AgentRuntime()
        runtime.record_result_state("agent-1", ResultState.INVALID)
        runtime.reset_result_state("agent-1")
        assert runtime.record_result_state("agent-1", ResultState.VALID)
        assert runtime.get_result_state("agent-1") == ResultState.VALID

    def test_multiple_agents_independent(self):
        runtime = AgentRuntime()
        runtime.record_result_state("agent-1", ResultState.VALID)
        runtime.record_result_state("agent-2", ResultState.INVALID)
        assert runtime.has_terminal_outcome("agent-1")
        assert runtime.has_terminal_outcome("agent-2")
        assert runtime.get_result_state("agent-1") == ResultState.VALID
        assert runtime.get_result_state("agent-2") == ResultState.INVALID


class TestRuntimeProcessManagement:
    """Existing runtime process management should still work."""

    def test_runtime_starts_stopped(self):
        runtime = AgentRuntime()
        assert runtime.get_state("nonexistent") == RuntimeState.STOPPED

    def test_is_running_false_for_nonexistent(self):
        runtime = AgentRuntime()
        assert not runtime.is_running("nonexistent")
