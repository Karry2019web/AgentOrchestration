"""Tests for trace aggregation with memory limit enforcement."""

import pytest
from src.common.trace import TraceAggregator, TraceEntry, DEFAULT_MEMORY_LIMIT_BYTES


class TestTraceEntry:
    def test_size_bytes_estimate(self):
        entry = TraceEntry("trace-1", "agent-1", "test.event", {"key": "value"})
        size = entry.size_bytes()
        assert size > 0
        assert isinstance(size, int)

    def test_to_dict(self):
        entry = TraceEntry("trace-1", "agent-1", "test.event", {"key": "value"})
        d = entry.to_dict()
        assert d["trace_id"] == "trace-1"
        assert d["agent_id"] == "agent-1"
        assert d["event"] == "test.event"
        assert d["payload"] == {"key": "value"}
        assert "timestamp" in d


class TestTraceAggregator:
    def setup_method(self):
        self.aggregator = TraceAggregator(memory_limit_bytes=1024)

    def test_initial_state(self):
        assert self.aggregator.entry_count == 0
        assert self.aggregator.current_size_bytes == 0
        assert self.aggregator.memory_limit_bytes == 1024
        assert self.aggregator.rejected_count == 0
        assert self.aggregator.has_capacity() is True

    def test_record_accepts_entry(self):
        result = self.aggregator.record("t1", "agent-1", "test.event")
        assert result is True
        assert self.aggregator.entry_count == 1

    def test_record_with_payload(self):
        result = self.aggregator.record("t2", "agent-2", "data.ready", {"size": 100})
        assert result is True
        assert self.aggregator.entry_count == 1

    def test_flush_returns_and_clears(self):
        self.aggregator.record("t1", "agent-1", "started")
        self.aggregator.record("t2", "agent-2", "completed")

        entries = self.aggregator.flush()
        assert len(entries) == 2
        assert self.aggregator.entry_count == 0
        assert self.aggregator.current_size_bytes == 0

    def test_memory_limit_rejects_overflow(self):
        """With a 1 KB limit, record enough entries to exceed it."""
        large_payload = {"data": "x" * 500}
        # First entry should fit
        assert self.aggregator.record("t1", "agent-1", "big.event", large_payload) is True
        # Keep adding until rejected
        accepted = 1
        while self.aggregator.has_capacity():
            accepted += 1
            r = self.aggregator.record(f"t{accepted}", "agent-1", "big.event", large_payload)
            if not r:
                break

        assert self.aggregator.rejected_count >= 1
        assert self.aggregator.entry_count < accepted

    def test_memory_limit_custom_threshold(self):
        tiny = TraceAggregator(memory_limit_bytes=100)
        assert tiny.record("t1", "a1", "tiny", {"x": "y"}) is True
        # This should fail with very small limit
        tiny.record("t2", "a1", "tiny", {"x": "y" * 200})
        # With 100 bytes, two small entries might still fit, but big payloads won't
        assert tiny.current_size_bytes <= tiny.memory_limit_bytes

    def test_snapshot_returns_state(self):
        self.aggregator.record("t1", "a1", "start")
        snap = self.aggregator.snapshot()
        assert snap["entry_count"] == 1
        assert snap["current_size_bytes"] > 0
        assert snap["memory_limit_bytes"] == 1024
        assert snap["rejected_count"] == 0
        assert snap["total_entries"] == 1
        assert 0 < snap["usage_pct"] <= 100

    def test_has_capacity(self):
        assert self.aggregator.has_capacity() is True
        # Fill to capacity
        big = {"data": "x" * 500}
        while self.aggregator.has_capacity():
            self.aggregator.record("tx", "ax", "fill", big)
        assert self.aggregator.has_capacity() is False


class TestTraceAggregatorDefaults:
    def test_default_memory_limit(self):
        agg = TraceAggregator()
        assert agg.memory_limit_bytes == DEFAULT_MEMORY_LIMIT_BYTES
        assert DEFAULT_MEMORY_LIMIT_BYTES == 4 * 1024 * 1024

    def test_accepts_large_batch_under_default(self):
        agg = TraceAggregator()
        for i in range(1000):
            r = agg.record(f"t{i}", f"agent-{i % 10}", "event", {"idx": i})
            assert r is True, f"Entry {i} rejected under default limit"

# 2026-05-23T09:50:00 update
