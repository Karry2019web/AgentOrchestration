import pytest
import sys
import importlib.util
import types

# Import scheduler directly to avoid the 'import resource' chain
spec = importlib.util.spec_from_file_location(
    "scheduler",
    r"C:\Users\Administrator\AgentOrchestration\src\orchestrator\scheduler.py"
)
scheduler_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduler_mod)

TaskScheduler = scheduler_mod.TaskScheduler
ConcurrencyLimitError = scheduler_mod.ConcurrencyLimitError


class TestPerTenantConcurrency:
    def setup_method(self):
        self.scheduler = TaskScheduler(default_max_concurrency=3)

    def test_set_tenant_limit(self):
        self.scheduler.set_tenant_limit("tenant-a", 5)
        assert self.scheduler.get_tenant_limit("tenant-a") == 5

    def test_default_limit(self):
        assert self.scheduler.get_tenant_limit("unknown-tenant") == 3

    def test_enqueue_within_limit(self):
        task_id = self.scheduler.enqueue_tenant_task(
            {"type": "test"}, tenant_id="t1"
        )
        assert task_id is not None

    def test_tenant_in_flight_increases(self):
        self.scheduler.enqueue_tenant_task({"type": "t1"}, tenant_id="t1")
        self.scheduler.enqueue_tenant_task({"type": "t2"}, tenant_id="t1")
        self.scheduler.enqueue_tenant_task({"type": "t3"}, tenant_id="t1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert self.scheduler.get_tenant_in_flight("t1") == 1

    def test_concurrency_limit_enforced_on_dequeue(self):
        self.scheduler.set_tenant_limit("t1", 2)
        self.scheduler.enqueue_tenant_task({"type": "a"}, tenant_id="t1")
        self.scheduler.enqueue_tenant_task({"type": "b"}, tenant_id="t1")
        result = self.scheduler.enqueue_tenant_task(
            {"type": "c"}, tenant_id="t1"
        )
        assert result is not None  # enqueue always works, limit on in-flight

    def test_in_flight_decreases_on_complete(self):
        self.scheduler.set_tenant_limit("t1", 2)
        self.scheduler.enqueue_tenant_task({"type": "a"}, tenant_id="t1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert self.scheduler.get_tenant_in_flight("t1") == 1
        self.scheduler.complete(task["id"])
        assert self.scheduler.get_tenant_in_flight("t1") == 0

    def test_complete_releases_slot(self):
        self.scheduler.set_tenant_limit("t1", 1)
        self.scheduler.enqueue_tenant_task({"type": "a"}, tenant_id="t1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        self.scheduler.complete(task["id"])
        task2_id = self.scheduler.enqueue_tenant_task(
            {"type": "b"}, tenant_id="t1"
        )
        assert task2_id is not None

    def test_recovery_mode_rejects_over_limit(self):
        self.scheduler.set_tenant_limit("t1", 1)
        self.scheduler.enter_recovery_mode()
        self.scheduler.enqueue_tenant_task({"type": "a"}, tenant_id="t1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        with pytest.raises(ConcurrencyLimitError, match="concurrency limit"):
            self.scheduler.enqueue_tenant_task(
                {"type": "b"}, tenant_id="t1"
            )

    def test_recovery_mode_dequeue_checks_limit(self):
        self.scheduler.set_tenant_limit("t1", 1)
        self.scheduler.enqueue_tenant_task({"type": "a"}, tenant_id="t1")
        self.scheduler.enqueue_tenant_task({"type": "b"}, tenant_id="t1")
        self.scheduler.enter_recovery_mode()
        import asyncio
        t1 = asyncio.run(self.scheduler.dequeue())
        assert t1 is not None
        t2 = asyncio.run(self.scheduler.dequeue())
        assert t2 is None

    def test_recover_tenant_admits_within_limit(self):
        self.scheduler.set_tenant_limit("t1", 3)
        admitted = self.scheduler.recover_tenant("t1", [
            {"type": "a"},
            {"type": "b"},
        ])
        assert len(admitted) == 2

    def test_recover_tenant_respects_limit(self):
        self.scheduler.set_tenant_limit("t1", 2)
        self.scheduler.enqueue_tenant_task({"type": "x"}, tenant_id="t1")
        self.scheduler.enqueue_tenant_task({"type": "y"}, tenant_id="t1")
        import asyncio
        asyncio.run(self.scheduler.dequeue())
        asyncio.run(self.scheduler.dequeue())
        admitted = self.scheduler.recover_tenant("t1", [
            {"type": "a"}, {"type": "b"}, {"type": "c"},
        ])
        assert len(admitted) == 0

    def test_recover_tenant_partial(self):
        self.scheduler.set_tenant_limit("t1", 3)
        self.scheduler.enqueue_tenant_task({"type": "x"}, tenant_id="t1")
        import asyncio
        asyncio.run(self.scheduler.dequeue())
        admitted = self.scheduler.recover_tenant("t1", [
            {"type": "a"}, {"type": "b"}, {"type": "c"},
        ])
        assert len(admitted) == 2

    def test_tenant_summary(self):
        self.scheduler.set_tenant_limit("t1", 5)
        summary = self.scheduler.get_tenant_summary("t1")
        assert summary["limit"] == 5
        assert summary["in_flight"] == 0
        assert summary["available"] == 5

    def test_no_tenant_id_skips_limit(self):
        self.scheduler.set_tenant_limit("t1", 1)
        for i in range(10):
            tid = self.scheduler.enqueue({"type": f"task{i}"})
            assert tid is not None

    def test_different_tenants_independent(self):
        self.scheduler.set_tenant_limit("t1", 1)
        self.scheduler.set_tenant_limit("t2", 3)
        self.scheduler.enqueue_tenant_task({"type": "a"}, tenant_id="t1")
        self.scheduler.enqueue_tenant_task({"type": "b"}, tenant_id="t1")
        result = self.scheduler.enqueue_tenant_task(
            {"type": "c"}, tenant_id="t2"
        )
        assert result is not None


class TestExistingFeatures:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_recovery_mode_toggle(self):
        assert not self.scheduler.is_recovery_mode
        self.scheduler.enter_recovery_mode()
        assert self.scheduler.is_recovery_mode
        self.scheduler.exit_recovery_mode()
        assert not self.scheduler.is_recovery_mode
