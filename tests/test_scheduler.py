import pytest
from src.orchestrator.scheduler import TaskScheduler
from src.common.errors import MalformedTaskPayloadError


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

    # --- Payload validation tests ---

    def test_reject_non_dict_task(self):
        """Regression: legacy queue records must reject non-dict payloads."""
        with pytest.raises(MalformedTaskPayloadError):
            self.scheduler.enqueue("not_a_dict")  # type: ignore[arg-type]

    def test_reject_missing_required_fields(self):
        """Regression: tasks without type and payload fields must be rejected."""
        with pytest.raises(MalformedTaskPayloadError):
            self.scheduler.enqueue({"id": "abc"})

    def test_reject_missing_type_field(self):
        """Regression: task missing 'type' field must be rejected."""
        with pytest.raises(MalformedTaskPayloadError):
            self.scheduler.enqueue({"payload": {}})

    def test_reject_non_dict_payload(self):
        """Regression: payload must be a dict, not a string or number."""
        with pytest.raises(MalformedTaskPayloadError):
            self.scheduler.enqueue({"type": "test", "payload": "invalid_string"})

    def test_reject_none_type(self):
        """Regression: type field must be present, None is not acceptable."""
        with pytest.raises(MalformedTaskPayloadError):
            self.scheduler.enqueue({"type": None, "payload": {}})

    # --- Idempotent retry tests ---

    def test_fail_after_complete_is_noop(self):
        """Regression: fail() after complete() must not re-enqueue the task."""
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        task_id = task["id"]
        self.scheduler.complete(task_id)
        assert not self.scheduler.fail(task_id), "fail after complete must return False"

    def test_idempotent_retry_does_not_duplicate(self):
        """Regression: calling fail() twice on same task must only enqueue once."""
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        task_id = task["id"]
        # First fail -> should enqueue retry
        assert self.scheduler.fail(task_id)
        # Dequeue the retry
        retry = asyncio.run(self.scheduler.dequeue())
        assert retry is not None
        assert retry["type"] == "test"
        # Second fail with original task_id must not re-enqueue
        assert not self.scheduler.fail(task_id), "duplicate fail must return False"

    def test_complete_removed_task_returns_false(self):
        """complete() on unknown id must return False gracefully."""
        assert not self.scheduler.complete("nonexistent-id")

    def test_fail_removed_task_returns_false(self):
        """fail() on unknown id must return False gracefully."""
        assert not self.scheduler.fail("nonexistent-id")
