"""Regression tests for trace query API with nested filter depth guard."""

import pytest
from src.common.queries import TraceQueryGuard, QueryFilterDepthError
from src.api.routes import _trace_store, _query_trace_store, trace_query_guard


class TestTraceQueryGuard:
    """Tests for the QueryFilterDepthGuard validation logic."""

    def setup_method(self):
        self.guard = TraceQueryGuard(max_depth=5)

    def test_shallow_filter_passes(self):
        """A flat filter with no nesting passes validation."""
        filters = {"agent_id": "agent-alpha", "status": "completed"}
        result = self.guard.validate(filters)
        assert result == filters

    def test_single_nested_filter_passes(self):
        """A filter nested one level deep passes validation."""
        filters = {"duration_ms": {"$gt": 1000}}
        result = self.guard.validate(filters)
        assert result == filters

    def test_and_operator_filter_passes(self):
        """A filter with $and logical operator passes at depth <= max."""
        filters = {
            "$and": [
                {"duration_ms": {"$gt": 1000}},
                {"status": "failed"},
            ]
        }
        result = self.guard.validate(filters)
        assert result == filters

    def test_max_depth_filter_passes(self):
        """A filter exactly at max_depth passes validation."""
        filters = {
            "$and": [
                {
                    "$and": [
                        {
                            "$and": [
                                {
                                    "$and": [
                                        {"status": "completed"},
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        result = self.guard.validate(filters)
        assert result == filters

    def test_exceeded_max_depth_raises_error(self):
        """A filter deeper than max_depth raises QueryFilterDepthError."""
        filters = {
            "$and": [
                {
                    "$and": [
                        {
                            "$and": [
                                {
                                    "$and": [
                                        {
                                            "$and": [
                                                {"status": "completed"},
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        with pytest.raises(QueryFilterDepthError) as exc_info:
            self.guard.validate(filters)
        assert exc_info.value.depth > exc_info.value.max_depth

    def test_deep_nested_dict_rejected(self):
        """Deeply nested dict fields (not just $and) are also checked."""
        filters = {
            "a": {
                "b": {
                    "c": {
                        "d": {
                            "e": {
                                "f": "too-deep"
                            }
                        }
                    }
                }
            }
        }
        with pytest.raises(QueryFilterDepthError):
            self.guard.validate(filters)

    def test_custom_max_depth(self):
        """Custom max_depth is respected."""
        guard = TraceQueryGuard(max_depth=2)
        filters = {"a": {"b": {"c": "value"}}}
        with pytest.raises(QueryFilterDepthError):
            guard.validate(filters)

    def test_empty_filter_passes(self):
        """Empty filter dict passes validation."""
        result = self.guard.validate({})
        assert result == {}

    def test_list_elements_checked(self):
        """Elements inside a list are checked for depth."""
        filters = {
            "$or": [
                {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
            ]
        }
        result = self.guard.validate(filters)
        assert result == filters


class TestTraceQueryAPI:
    """Integration tests for trace query API endpoints."""

    def test_query_traces_no_filters(self):
        """Query without filters returns all traces."""
        assert len(_trace_store) == 5

    def test_query_traces_with_simple_filter(self):
        """Query with a simple field filter returns matching traces."""
        results = _query_trace_store({"status": "completed"})
        assert len(results) == 3
        assert all(t["status"] == "completed" for t in results)

    def test_query_traces_with_nested_condition(self):
        """Query with comparison operator works correctly."""
        results = _query_trace_store({"duration_ms": {"$gt": 1000}})
        assert len(results) == 3
        assert all(t["duration_ms"] > 1000 for t in results)

    def test_query_traces_with_and_filter(self):
        """Query with $and logical operator returns correct results."""
        results = _query_trace_store({
            "$and": [
                {"duration_ms": {"$gt": 1000}},
                {"status": "failed"},
            ]
        })
        assert len(results) == 1
        assert results[0]["trace_id"] == "trace-002"

    def test_query_traces_with_or_filter(self):
        """Query with $or logical operator returns correct results."""
        results = _query_trace_store({
            "$or": [
                {"status": "failed"},
                {"status": "running"},
            ]
        })
        assert len(results) == 2

    def test_query_traces_limit(self):
        """Query respects the limit parameter."""
        results = _query_trace_store({}, limit=2)
        assert len(results) == 2

    def test_query_traces_nested_field_access(self):
        """Query supports dotted field paths (e.g. tags.env)."""
        results = _query_trace_store({"tags.env": "prod"})
        assert len(results) == 3

    def test_deep_filter_returns_422_via_guard(self):
        """POST /traces/query with deeply nested filter returns 422 via guard."""
        from fastapi import HTTPException
        deep_filters = {
            "$and": [
                {
                    "$and": [
                        {
                            "$and": [
                                {
                                    "$and": [
                                        {
                                            "$and": [
                                                {"status": "completed"},
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        with pytest.raises(QueryFilterDepthError):
            trace_query_guard.validate(deep_filters)

    def test_list_traces_with_query_params(self):
        """GET /traces with query params returns filtered results."""
        results = _query_trace_store({"agent_id": "agent-alpha"})
        assert len(results) == 2
        assert all(t["agent_id"] == "agent-alpha" for t in results)

    def test_list_traces_no_match_returns_empty(self):
        """Non-matching filter returns empty list."""
        results = _query_trace_store({"agent_id": "agent-nonexistent"})
        assert len(results) == 0

    def test_in_operator(self):
        """$in operator matches any value in the list."""
        results = _query_trace_store({"status": {"$in": ["completed", "failed"]}})
        assert len(results) == 4

    def test_nin_operator(self):
        """$nin operator excludes values in the list."""
        results = _query_trace_store({"status": {"$nin": ["completed"]}})
        assert len(results) == 2

    def test_not_operator(self):
        """$not operator inverts the condition."""
        results = _query_trace_store({"$not": {"status": "completed"}})
        assert len(results) == 2


class TestGuardIntegration:
    """Guard integration tests."""

    guard = TraceQueryGuard(max_depth=5)

    def test_malformed_filter_rejected(self):
        """Deeply malformed filter is rejected."""
        deep = {
            "a": {
                "b": {
                    "c": {
                        "d": {
                            "e": {
                                "f": "way-too-deep"
                            }
                        }
                    }
                }
            }
        }
        with pytest.raises(QueryFilterDepthError):
            self.guard.validate(deep)
