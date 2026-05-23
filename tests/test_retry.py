"""Tests for RetryTracker — attempt-scoped retry counters and parallel branch retry isolation."""

import pytest
from src.orchestrator.retry import RetryTracker
from src.orchestrator.workflow import RetryScope, ParallelBranch, WorkflowManager


class TestRetryTracker:
    """Tests for the core RetryTracker class."""

    def test_initial_retry_count_is_zero(self):
        tracker = RetryTracker(max_retries=3)
        assert tracker.get_retry_count("task-1") == 0
        assert tracker.get_retry_count("task-1", "branch-a") == 0

    def test_increment_increases_count(self):
        tracker = RetryTracker(max_retries=3)
        tracker.increment("task-1")
        assert tracker.get_retry_count("task-1") == 1
        tracker.increment("task-1")
        assert tracker.get_retry_count("task-1") == 2

    def test_can_retry_when_under_limit(self):
        tracker = RetryTracker(max_retries=3)
        assert tracker.can_retry("task-1") is True
        tracker.increment("task-1")
        tracker.increment("task-1")
        assert tracker.can_retry("task-1") is True

    def test_cannot_retry_when_at_limit(self):
        tracker = RetryTracker(max_retries=3)
        for _ in range(3):
            tracker.increment("task-1")
        assert tracker.can_retry("task-1") is False

    def test_parallel_branches_have_isolated_counters(self):
        """Parallel branches with different attempt_ids should NOT share retry counts."""
        tracker = RetryTracker(max_retries=3)
        tracker.increment("task-1", "branch-a")
        tracker.increment("task-1", "branch-a")
        assert tracker.get_retry_count("task-1", "branch-a") == 2
        assert tracker.get_retry_count("task-1", "branch-b") == 0
        assert tracker.can_retry("task-1", "branch-b") is True
        tracker.increment("task-1", "branch-b")
        assert tracker.get_retry_count("task-1", "branch-b") == 1
        assert tracker.get_retry_count("task-1", "branch-a") == 2

    def test_branch_a_exhaustion_does_not_affect_branch_b(self):
        tracker = RetryTracker(max_retries=2)
        tracker.increment("task-1", "branch-a")
        tracker.increment("task-1", "branch-a")
        assert tracker.can_retry("task-1", "branch-a") is False
        assert tracker.can_retry("task-1", "branch-b") is True
        tracker.increment("task-1", "branch-b")
        assert tracker.get_retry_count("task-1", "branch-b") == 1

    def test_reset_clears_all_attempts(self):
        tracker = RetryTracker(max_retries=3)
        tracker.increment("task-1", "branch-a")
        tracker.increment("task-1", "branch-b")
        tracker.reset("task-1")
        assert tracker.get_retry_count("task-1", "branch-a") == 0
        assert tracker.get_retry_count("task-1", "branch-b") == 0

    def test_reset_attempt_clears_one_branch(self):
        tracker = RetryTracker(max_retries=3)
        tracker.increment("task-1", "branch-a")
        tracker.increment("task-1", "branch-b")
        tracker.reset_attempt("task-1", "branch-a")
        assert tracker.get_retry_count("task-1", "branch-a") == 0
        assert tracker.get_retry_count("task-1", "branch-b") == 1

    def test_remaining_returns_correct_value(self):
        tracker = RetryTracker(max_retries=5)
        assert tracker.remaining("task-1") == 5
        tracker.increment("task-1")
        assert tracker.remaining("task-1") == 4
        for _ in range(4):
            tracker.increment("task-1")
        assert tracker.remaining("task-1") == 0

    def test_different_tasks_have_independent_counters(self):
        tracker = RetryTracker(max_retries=3)
        tracker.increment("task-1")
        tracker.increment("task-1")
        assert tracker.get_retry_count("task-2") == 0
        assert tracker.can_retry("task-2") is True


class TestSchedulerRetryIntegration:
    """Tests for TaskScheduler fail() with attempt-scoped retry IDs."""

    def test_fail_with_default_attempt_id(self):
        from src.orchestrator.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        import asyncio
        scheduler._max_retries = 3
        scheduler.enqueue({"type": "test", "payload": {}})
        task = asyncio.run(scheduler.dequeue())
        assert scheduler.fail(task["id"]) is True
        assert scheduler.get_retry_count(task["id"]) == 1
        task2 = asyncio.run(scheduler.dequeue())
        assert scheduler.fail(task2["id"]) is True
        assert scheduler.get_retry_count(task2["id"]) == 2
        task3 = asyncio.run(scheduler.dequeue())
        assert scheduler.fail(task3["id"]) is True
        assert scheduler.get_retry_count(task3["id"]) == 3
        task4 = asyncio.run(scheduler.dequeue())
        assert scheduler.fail(task4["id"]) is False

    def test_fail_with_parallel_attempt_ids(self):
        from src.orchestrator.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        import asyncio
        scheduler._max_retries = 2
        scheduler.enqueue({"type": "parent"})
        task = asyncio.run(scheduler.dequeue())
        assert scheduler.fail(task["id"], attempt_id="branch-a") is True
        assert scheduler.get_retry_count(task["id"], "branch-a") == 1
        assert scheduler.fail(task["id"], attempt_id="branch-b") is True
        assert scheduler.get_retry_count(task["id"], "branch-b") == 1
        assert scheduler.get_retry_count(task["id"], "branch-a") == 1

    def test_complete_resets_all_counters(self):
        from src.orchestrator.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        import asyncio
        scheduler._max_retries = 3
        scheduler.enqueue({"type": "test"})
        task = asyncio.run(scheduler.dequeue())
        scheduler.fail(task["id"], attempt_id="branch-a")
        scheduler.fail(task["id"], attempt_id="branch-b")
        assert scheduler.get_retry_count(task["id"], "branch-a") == 1
        assert scheduler.get_retry_count(task["id"], "branch-b") == 1
        scheduler.complete(task["id"])
        assert scheduler.get_retry_count(task["id"], "branch-a") == 0
        assert scheduler.get_retry_count(task["id"], "branch-b") == 0


class TestRetryScope:
    def test_initial_state(self):
        scope = RetryScope("task-1", "branch-a", max_retries=3)
        assert scope.attempt == 0
        assert scope.can_retry() is True
        assert scope.remaining() == 3

    def test_recording_attempts(self):
        scope = RetryScope("task-1", "branch-a", max_retries=3)
        assert scope.record_attempt() == 1
        assert scope.attempt == 1
        assert scope.remaining() == 2

    def test_exhaustion(self):
        scope = RetryScope("task-1", "branch-a", max_retries=2)
        scope.record_attempt()
        scope.record_attempt()
        assert scope.can_retry() is False
        assert scope.remaining() == 0

    def test_zero_max_retries(self):
        scope = RetryScope("task-1", "branch-a", max_retries=0)
        assert scope.can_retry() is False


class TestParallelBranchExecution:
    def test_branch_succeeds_first_attempt(self):
        manager = WorkflowManager()
        def handler():
            return "ok"
        branch = ParallelBranch("branch-a", handler)
        result = manager.execute_parallel_branch(branch, "task-1", "attempt-1")
        assert result is True
        assert branch.status.name == "COMPLETED"

    def test_branch_fails_then_retries(self):
        manager = WorkflowManager()
        call_count = [0]
        def handler():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("transient error")
            return "ok"
        branch = ParallelBranch("branch-a", handler, retries=2)
        result = manager.execute_parallel_branch(branch, "task-1", "attempt-1", max_retries=2)
        assert result is True
        assert call_count[0] == 2

    def test_branch_exhausts_retries(self):
        manager = WorkflowManager()
        call_count = [0]
        def handler():
            call_count[0] += 1
            raise ValueError("persistent error")
        branch = ParallelBranch("branch-a", handler, retries=2)
        result = manager.execute_parallel_branch(branch, "task-1", "attempt-1", max_retries=2)
        assert result is False
        assert call_count[0] == 2

    def test_isolated_branch_retries(self):
        manager = WorkflowManager()
        branch_a_calls = [0]
        branch_b_calls = [0]
        def handler_a():
            branch_a_calls[0] += 1
            raise ValueError("branch a always fails")
        def handler_b():
            branch_b_calls[0] += 1
            if branch_b_calls[0] < 2:
                raise ValueError("branch b transient")
            return "ok"
        branch_a = ParallelBranch("branch-a", handler_a, retries=2)
        branch_b = ParallelBranch("branch-b", handler_b, retries=2)
        result_a = manager.execute_parallel_branch(branch_a, "task-1", "branch-a", max_retries=2)
        result_b = manager.execute_parallel_branch(branch_b, "task-1", "branch-b", max_retries=2)
        assert result_a is False
        assert result_b is True
        assert branch_a_calls[0] == 2
        assert branch_b_calls[0] == 2
