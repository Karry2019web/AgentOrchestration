"""Tests for reconciliation stagger guard — covers #3288."""

import time
import pytest
from src.orchestrator.scheduler import TaskScheduler, JitterConfig, ReconciliationAuditEntry


class TestReconciliationStagger:
    """Deterministic regression tests for cluster-startup stagger."""

    def test_stagger_offset_is_predictable(self):
        """Same node_id produces the same jitter offset (deterministic)."""
        cfg1 = JitterConfig(node_id="node-alpha", stagger_window=120.0)
        cfg2 = JitterConfig(node_id="node-alpha", stagger_window=120.0)
        s1 = TaskScheduler(jitter_config=cfg1)
        s2 = TaskScheduler(jitter_config=cfg2)
        assert s1.jitter_offset == s2.jitter_offset

    def test_different_nodes_have_different_offsets(self):
        """Different node_ids produce different jitter offsets (spread)."""
        cfg1 = JitterConfig(node_id="node-alpha", stagger_window=120.0)
        cfg2 = JitterConfig(node_id="node-beta", stagger_window=120.0)
        s1 = TaskScheduler(jitter_config=cfg1)
        s2 = TaskScheduler(jitter_config=cfg2)
        assert s1.jitter_offset != s2.jitter_offset

    def test_offset_is_within_stagger_window(self):
        """Jitter offset must be in [0, stagger_window)."""
        for node_id in ["a", "b", "c", "node-100", "orch-node-42"]:
            cfg = JitterConfig(node_id=node_id, stagger_window=60.0)
            s = TaskScheduler(jitter_config=cfg)
            assert 0 <= s.jitter_offset < 60.0, f"Offset {s.jitter_offset} out of range for {node_id}"

    def test_startup_defer_before_first_run(self):
        """Reconciliation is deferred before jitter_offset elapses."""
        cfg = JitterConfig(node_id="test-node", stagger_window=60.0, base_interval=300.0)
        scheduler = TaskScheduler(jitter_config=cfg)
        call_count = 0
        def cb():
            nonlocal call_count
            call_count += 1
        scheduler.setup_periodic_task("reconcile", cb)
        # Immediately after creation, first_run_at = startup + jitter_offset > now
        result = scheduler.run_periodic_task("reconcile")
        assert result == "deferred", f"Expected deferred, got {result}"
        assert call_count == 0

    def test_accept_after_startup_window(self):
        """Reconciliation is accepted after the jitter_offset has elapsed."""
        cfg = JitterConfig(node_id="test-node", stagger_window=0.001, base_interval=0.01)
        scheduler = TaskScheduler(jitter_config=cfg)
        call_count = 0
        def cb():
            nonlocal call_count
            call_count += 1
        scheduler.setup_periodic_task("reconcile", cb)
        # Wait for stagger window to pass (very small)
        time.sleep(0.01)
        result = scheduler.run_periodic_task("reconcile")
        assert result == "accepted", f"Expected accepted, got {result}"
        assert call_count == 1

    def test_interval_enforcement(self):
        """Subsequent reconciliation within base_interval is deferred."""
        cfg = JitterConfig(node_id="test-node", stagger_window=0.001, base_interval=10.0)
        scheduler = TaskScheduler(jitter_config=cfg)
        call_count = 0
        def cb():
            nonlocal call_count
            call_count += 1
        scheduler.setup_periodic_task("reconcile", cb)
        time.sleep(0.01)
        # First — should be accepted
        result1 = scheduler.run_periodic_task("reconcile")
        assert result1 == "accepted"
        assert call_count == 1
        # Second — should be deferred (10s interval not elapsed)
        result2 = scheduler.run_periodic_task("reconcile")
        assert result2 == "deferred", f"Expected deferred, got {result2}"
        assert call_count == 1  # Callback should NOT be invoked

    def test_accept_after_interval_elapsed(self):
        """After base_interval passes, reconciliation is accepted again."""
        cfg = JitterConfig(node_id="test-node", stagger_window=0.001, base_interval=0.02)
        scheduler = TaskScheduler(jitter_config=cfg)
        call_count = 0
        def cb():
            nonlocal call_count
            call_count += 1
        scheduler.setup_periodic_task("reconcile", cb)
        time.sleep(0.01)
        assert scheduler.run_periodic_task("reconcile") == "accepted"
        assert call_count == 1
        time.sleep(0.03)  # Wait past base_interval
        result2 = scheduler.run_periodic_task("reconcile")
        assert result2 == "accepted", f"Expected accepted, got {result2}"
        assert call_count == 2

    def test_unknown_task_rejected(self):
        """Calling run_periodic_task for an unregistered task returns rejected."""
        scheduler = TaskScheduler()
        result = scheduler.run_periodic_task("nonexistent")
        assert result == "rejected"

    def test_audit_log_entries(self):
        """Audit log records decisions with bounded metadata."""
        cfg = JitterConfig(node_id="audit-node", stagger_window=0.001, base_interval=10.0, max_audit_entries=256)
        scheduler = TaskScheduler(jitter_config=cfg)
        def cb():
            pass
        scheduler.setup_periodic_task("reconcile", cb)
        time.sleep(0.01)
        scheduler.run_periodic_task("reconcile")
        entries = scheduler.get_audit_log()
        assert len(entries) >= 1
        entry = entries[0]
        assert isinstance(entry, ReconciliationAuditEntry)
        assert entry.node_id == "audit-node"
        assert entry.action in ("accepted", "deferred", "rejected")
        assert isinstance(entry.timestamp, float)
        assert entry.timestamp > 0
        assert isinstance(entry.reason, str)
        assert len(entry.reason) > 0
        # Verify no private data exposed
        assert "token" not in entry.reason.lower()
        assert "secret" not in entry.reason.lower()
        assert "password" not in entry.reason.lower()

    def test_audit_log_ring_buffer_respected(self):
        """Audit log does not exceed max_audit_entries."""
        cfg = JitterConfig(node_id="ring-node", stagger_window=0.001, base_interval=0.001, max_audit_entries=5)
        scheduler = TaskScheduler(jitter_config=cfg)
        def cb():
            pass
        scheduler.setup_periodic_task("reconcile", cb)
        # Run many times (wait small intervals so they're accepted)
        for _ in range(10):
            time.sleep(0.002)
            scheduler.run_periodic_task("reconcile")
        entries = scheduler.get_audit_log()
        assert len(entries) <= 5

    def test_audit_log_clear(self):
        """clear_audit_log empties the ring buffer."""
        cfg = JitterConfig(node_id="clear-node", stagger_window=0.001, base_interval=10.0)
        scheduler = TaskScheduler(jitter_config=cfg)
        def cb():
            pass
        scheduler.setup_periodic_task("reconcile", cb)
        time.sleep(0.01)
        scheduler.run_periodic_task("reconcile")
        assert len(scheduler.get_audit_log()) > 0
        scheduler.clear_audit_log()
        assert len(scheduler.get_audit_log()) == 0

    def test_backward_compatibility(self):
        """TaskScheduler without JitterConfig works exactly as before."""
        s = TaskScheduler()
        task_id = s.enqueue({"type": "legacy"}, queue="test")
        assert task_id is not None
        import asyncio
        task = asyncio.run(s.dequeue("test"))
        assert task is not None
        assert task["type"] == "legacy"
        assert s.complete(task["id"])
