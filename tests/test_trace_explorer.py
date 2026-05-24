import pytest
from src.api.trace_explorer import (
    TraceExplorer,
    FilterDepthError,
    validate_filter_depth,
    MAX_FILTER_DEPTH,
    get_explorer,
)


class TestValidateFilterDepth:
    def test_flat_filter_passes(self):
        validate_filter_depth({"status": "completed"})

    def test_two_level_depth_passes(self):
        validate_filter_depth({"and": [{"status": "completed"}, {"type": "task"}]})

    def test_three_level_max_depth_passes(self):
        validate_filter_depth({
            "and": [
                {"status": "completed"},
                {"or": [{"type": "task"}, {"priority": "high"}]},
            ]
        })

    def test_exceeds_max_depth_raises(self):
        with pytest.raises(FilterDepthError):
            validate_filter_depth({
                "and": [
                    {
                        "and": [
                            {
                                "and": [
                                    {"status": "completed"},
                                    {"type": "task"},
                                ]
                            }
                        ]
                    }
                ]
            })

    def test_deeply_nested_not_raises(self):
        with pytest.raises(FilterDepthError):
            validate_filter_depth({
                "not": {
                    "and": [
                        {"not": {"status": "failed"}},
                        {"and": [{"type": "test"}]},
                    ]
                }
            })

    def test_empty_filter_passes(self):
        validate_filter_depth({})

    def test_none_filter_passes(self):
        validate_filter_depth(None)


class TestTraceExplorer:
    def setup_method(self):
        self.explorer = TraceExplorer()
        self.explorer.record("agent-1", {"id": "t1", "type": "task", "status": "completed", "timestamp": 100})
        self.explorer.record("agent-1", {"id": "t2", "type": "task", "status": "failed", "timestamp": 200})
        self.explorer.record("agent-2", {"id": "t3", "type": "event", "status": "completed", "timestamp": 150})

    def test_query_all(self):
        results = self.explorer.query()
        assert len(results) == 3

    def test_query_with_filter(self):
        results = self.explorer.query(filters={"status": "completed"})
        assert len(results) == 2

    def test_query_with_and_filter(self):
        results = self.explorer.query(filters={
            "and": [{"status": "completed"}, {"type": "task"}],
        })
        assert len(results) == 1
        assert results[0]["id"] == "t1"

    def test_query_with_or_filter(self):
        results = self.explorer.query(filters={
            "or": [{"status": "failed"}, {"type": "event"}],
        })
        assert len(results) == 2

    def test_query_with_not_filter(self):
        results = self.explorer.query(filters={"not": {"status": "failed"}})
        assert len(results) == 2

    def test_query_filter_depth_raises(self):
        with pytest.raises(FilterDepthError):
            self.explorer.query(filters={
                "and": [
                    {
                        "and": [
                            {
                                "and": [
                                    {"status": "completed"},
                                ]
                            }
                        ]
                    }
                ]
            })

    def test_query_limit(self):
        results = self.explorer.query(limit=1)
        assert len(results) == 1

    def test_query_offset(self):
        results = self.explorer.query(offset=2)
        assert len(results) == 1

    def test_query_invalid_limit(self):
        with pytest.raises(ValueError):
            self.explorer.query(limit=0)

    def test_query_invalid_offset(self):
        with pytest.raises(ValueError):
            self.explorer.query(offset=-1)

    def test_get_by_id_found(self):
        trace = self.explorer.get_by_id("t1")
        assert trace is not None
        assert trace["id"] == "t1"

    def test_get_by_id_not_found(self):
        trace = self.explorer.get_by_id("nonexistent")
        assert trace is None

    def test_get_by_id_empty(self):
        explorer = TraceExplorer()
        assert explorer.get_by_id("anything") is None


class TestGetExplorer:
    def test_singleton(self):
        e1 = get_explorer()
        e2 = get_explorer()
        assert e1 is e2
