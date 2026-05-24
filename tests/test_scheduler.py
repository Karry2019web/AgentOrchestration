import pytest
from src.orchestrator.scheduler import TaskScheduler, WorkerProtocolSettings


class TestWorkerProtocolSettings:
    def test_valid_settings(self):
        settings = WorkerProtocolSettings(ack_timeout=30.0, visibility_timeout=10.0)
        assert settings.ack_timeout == 30.0
        assert settings.visibility_timeout == 10.0

    def test_ack_timeout_must_exceed_visibility(self):
        with pytest.raises(ValueError, match="ack_timeout.*must exceed.*visibility_timeout"):
            WorkerProtocolSettings(ack_timeout=5.0, visibility_timeout=10.0)

    def test_equal_timeouts_raises(self):
        with pytest.raises(ValueError, match="ack_timeout.*must exceed.*visibility_timeout"):
            WorkerProtocolSettings(ack_timeout=10.0, visibility_timeout=10.0)

    def test_zero_visibility_valid(self):
        settings = WorkerProtocolSettings(ack_timeout=1.0, visibility_timeout=0.0)
        assert settings.ack_timeout > settings.visibility_timeout

    def test_default_settings(self):
        settings = WorkerProtocolSettings()
        assert settings.ack_timeout == 30.0
        assert settings.visibility_timeout == 10.0
        assert settings.ack_timeout > settings.visibility_timeout

    def test_repr(self):
        settings = WorkerProtocolSettings(ack_timeout=60.0, visibility_timeout=15.0)
        r = repr(settings)
        assert "ack_timeout=60.0" in r
        assert "visibility_timeout=15.0" in r


class TestTaskScheduler:
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

    def test_enqueued_task_has_protocol_timeouts(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert "ack_timeout" in task
        assert "visibility_timeout" in task
        assert task["ack_timeout"] == 30.0
        assert task["visibility_timeout"] == 10.0

    def test_custom_protocol_settings(self):
        s = TaskScheduler(protocol_settings=WorkerProtocolSettings(ack_timeout=60.0, visibility_timeout=20.0))
        s.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(s.dequeue())
        assert task["ack_timeout"] == 60.0
        assert task["visibility_timeout"] == 20.0

    def test_protocol_property(self):
        settings = WorkerProtocolSettings(ack_timeout=45.0, visibility_timeout=15.0)
        s = TaskScheduler(protocol_settings=settings)
        assert s.protocol is settings
