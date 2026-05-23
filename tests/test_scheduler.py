"""Tests for task scheduler."""

import pytest
from src.orchestrator.scheduler import TaskScheduler, LeaderEpoch


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

    def test_emit_cron_tick_accepted(self):
        assert self.scheduler.emit_cron_tick("tick-1") is True

    def test_emit_cron_tick_duplicate_rejected(self):
        assert self.scheduler.emit_cron_tick("tick-1") is True
        assert self.scheduler.emit_cron_tick("tick-1") is False

    def test_emit_cron_tick_leader_change_rejects_old_epoch(self):
        assert self.scheduler.emit_cron_tick("tick-1") is True
        self.scheduler.advance_leader_epoch()
        # tick from old epoch should be rejected
        assert self.scheduler.emit_cron_tick("tick-1") is False

    def test_emit_cron_tick_new_epoch_accepted(self):
        self.scheduler.advance_leader_epoch()
        assert self.scheduler.emit_cron_tick("tick-2") is True

    def test_leader_epoch_advance(self):
        assert self.scheduler.leader_epoch.epoch == 0
        self.scheduler.advance_leader_epoch()
        assert self.scheduler.leader_epoch.epoch == 1

    def test_leader_epoch_prune(self):
        epoch = self.scheduler.leader_epoch
        epoch.witness("a", 0)
        epoch.witness("b", 0)
        epoch.advance()
        epoch.witness("c", 1)
        pruned = epoch.prune(older_than_epoch=1)
        assert pruned == 2


class TestLeaderEpoch:
    def test_witness_rejects_duplicate(self):
        epoch = LeaderEpoch()
        assert epoch.witness("t1", 0) is True
        assert epoch.witness("t1", 0) is False

    def test_witness_rejects_stale_epoch(self):
        epoch = LeaderEpoch()
        epoch.advance()  # now epoch = 1
        assert epoch.witness("t1", 0) is False

    def test_prune_removes_old_entries(self):
        epoch = LeaderEpoch()
        epoch.witness("a", 0)
        epoch.witness("b", 0)
        epoch.advance()
        epoch.witness("c", 1)
        assert epoch.prune(older_than_epoch=1) == 2
        assert epoch.prune(older_than_epoch=2) == 1

# 2026-05-23T23:52:00+08:00 update
