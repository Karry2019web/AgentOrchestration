"""Tests for TraceMemoryGuard memory-limited trace aggregation."""
import sys
from unittest.mock import MagicMock
sys.modules["resource"] = MagicMock()

# AgentStatus exists in registry.py but __init__.py doesn't export it
import src.agent
src.agent.AgentStatus = MagicMock()
src.agent.AgentRegistry = MagicMock()

import pytest
from src.orchestrator.tracing import (
    TraceMemoryGuard,
    MemoryExceeded,
    ClosedAggregation,
    AggState,
    Span,
)


def _span(sid="s1", op="step", size_hint="", wall_ms=0.0):
    return Span(id=sid, operation=op, wall_ms=wall_ms, tags={"data": size_hint})


class TestTraceMemoryGuard:

    def test_accepts_spans_within_limit(self):
        guard = TraceMemoryGuard(max_bytes=4096)
        guard.accept("run-1", _span("s1"))
        guard.accept("run-1", _span("s2"))
        snap = guard.snapshot("run-1")
        assert snap["state"] == "active"
        assert snap["span_count"] == 2

    def test_rejects_span_that_exceeds_limit(self):
        guard = TraceMemoryGuard(max_bytes=200)
        guard.accept("run-1", _span("s1", size_hint="small"))
        with pytest.raises(MemoryExceeded):
            guard.accept("run-1", _span("s2", size_hint="x" * 300))
        snap = guard.snapshot("run-1")
        assert snap["state"] == "rejected"
        assert snap["span_count"] == 1

    def test_terminal_state_rejects_further_writes(self):
        guard = TraceMemoryGuard(max_bytes=4096)
        guard.accept("run-1", _span("s1"))
        guard.complete("run-1")
        with pytest.raises(ClosedAggregation):
            guard.accept("run-1", _span("s2"))

    def test_cancel(self):
        guard = TraceMemoryGuard(max_bytes=4096)
        guard.accept("run-1", _span("s1"))
        outcome = guard.cancel("run-1", reason="timeout")
        assert outcome.state == AggState.CANCELLED

    def test_complete_returns_durable_outcome(self):
        guard = TraceMemoryGuard(max_bytes=4096)
        guard.accept("run-1", _span("s1"))
        outcome = guard.complete("run-1")
        assert outcome.state == AggState.COMPLETED
        assert outcome.span_count == 1
        assert outcome.bytes_used > 0

    def test_outcome_persisted(self):
        guard = TraceMemoryGuard(max_bytes=4096)
        guard.accept("run-1", _span("s1"))
        guard.complete("run-1")
        o = guard.outcome("run-1")
        assert o["state"] == "completed"

    def test_runs_independent(self):
        guard = TraceMemoryGuard(max_bytes=4096)
        guard.accept("run-a", _span("s1"))
        guard.accept("run-b", _span("s2"))
        assert guard.snapshot("run-a")["span_count"] == 1
        assert guard.snapshot("run-b")["span_count"] == 1

    def test_reset_clears(self):
        guard = TraceMemoryGuard(max_bytes=4096)
        guard.accept("run-1", _span("s1"))
        guard.reset()
        assert guard.snapshot("run-1") is None

    def test_concurrent_writes(self):
        import threading
        guard = TraceMemoryGuard(max_bytes=50000)
        def writer(run_id, count):
            for i in range(count):
                try:
                    guard.accept(run_id, _span(f"s{i}", size_hint="data"))
                except (MemoryExceeded, ClosedAggregation):
                    pass
        threads = [threading.Thread(target=writer, args=(f"run-{i%3}", 20))
                   for i in range(9)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for run_id in ["run-0", "run-1", "run-2"]:
            assert guard.snapshot(run_id)["span_count"] > 0
