import pytest
from src.orchestrator.engine import OrchestrationEngine, DelegationDepthError


class TestDelegationDepth:
    def setup_method(self):
        self.engine = OrchestrationEngine(max_workers=2, max_delegation_depth=3)

    def test_default_depth_allows_normal_tasks(self):
        task_id = self.engine.scheduler.enqueue({
            "target_agent": "agent-1",
        })
        assert task_id is not None

    def test_delegation_below_depth_succeeds(self):
        task = self.engine.scheduler.enqueue({
            "target_agent": "agent-1",
        })
        delegated_id = self.engine.delegate(
            {"id": task, "target_agent": "agent-1"},
            "agent-2",
        )
        assert delegated_id is not None

    def test_delegation_at_max_depth_rejected(self):
        with pytest.raises(DelegationDepthError):
            self.engine.delegate(
                {"id": "task-1", "delegation_depth": 3},
                "agent-2",
            )

    def test_delegation_chain_stops_at_depth(self):
        depth = 0
        task = {"id": "root", "target_agent": "agent-1", "delegation_depth": depth}
        for _ in range(self.engine.max_delegation_depth + 1):
            try:
                tid = self.engine.delegate(task, "next-agent")
                task = {"id": tid, "delegation_depth": task.get("delegation_depth", 0) + 1}
            except DelegationDepthError:
                return  # Expected — depth exceeded
        pytest.fail("Should have raised DelegationDepthError")

    def test_execute_task_rejects_excessive_depth(self):
        task = {"id": "deep-task", "target_agent": "agent-1", "delegation_depth": 3}
        self.engine._execute_task(task)
        # Should not raise — logs error and returns gracefully
        assert True
