"""Tests for trace query API validation."""

import pytest
import json
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.common.trace_query import (
    TraceQueryService,
    MAX_FILTER_DEPTH,
    NestedFilterDepthError,
    TraceQueryError,
)


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestTraceQueryService:
    """Unit tests for TraceQueryService validation logic."""

    def test_valid_flat_filter(self):
        """Authorized: simple flat filter passes validation."""
        result = TraceQueryService.parse_and_validate_query({
            "trace_type": "agent_execution",
            "filters": {"status": "completed", "agent_id": "agent-123"},
        })
        assert result["trace_type"] == "agent_execution"
        assert result["filters"]["status"] == "completed"

    def test_valid_nested_filter_within_limit(self):
        """Authorized: nested filter within MAX_FILTER_DEPTH passes."""
        params = TraceQueryService.parse_and_validate_query({
            "trace_type": "agent_execution",
            "filters": {
                "$and": [
                    {"status": "completed"},
                    {
                        "$or": [
                            {"duration": {"$gt": 100}},
                            {
                                "$and": [
                                    {"retry_count": {"$gt": 0}},
                                    {"priority": "high"},
                                ]
                            },
                        ]
                    },
                ]
            },
        })
        assert params["trace_type"] == "agent_execution"

    def test_valid_filter_max_depth(self):
        """Authorized: filter exactly at MAX_FILTER_DEPTH passes."""
        # Build a nested structure exactly at max depth
        filters = {"a": "1"}
        current = filters
        for i in range(MAX_FILTER_DEPTH):
            nested = {f"level_{i}": f"value_{i}"}
            current["$and"] = [nested]
            current = nested

        params = TraceQueryService.parse_and_validate_query({
            "trace_type": "agent_execution",
            "filters": filters,
        })
        assert params["trace_type"] == "agent_execution"

    def test_rejects_excessive_nested_depth(self):
        """Unauthorized: filter exceeding MAX_FILTER_DEPTH is rejected."""
        filters = {"a": "1"}
        current = filters
        for i in range(MAX_FILTER_DEPTH + 2):
            nested = {f"level_{i}": f"value_{i}"}
            current["$and"] = [nested]
            current = nested

        with pytest.raises(NestedFilterDepthError):
            TraceQueryService.parse_and_validate_query({
                "trace_type": "agent_execution",
                "filters": filters,
            })

    def test_rejects_missing_trace_type(self):
        """Malformed: missing trace_type is rejected."""
        with pytest.raises(TraceQueryError, match="Missing required field"):
            TraceQueryService.parse_and_validate_query({
                "filters": {"status": "completed"},
            })

    def test_rejects_non_dict_body(self):
        """Malformed: non-dict body is rejected."""
        with pytest.raises(TraceQueryError, match="must be a JSON object"):
            TraceQueryService.parse_and_validate_query("invalid")

    def test_rejects_non_dict_filters(self):
        """Malformed: non-dict filters are rejected."""
        with pytest.raises(TraceQueryError, match="must be a JSON object"):
            TraceQueryService.parse_and_validate_query({
                "trace_type": "test",
                "filters": "invalid_string",
            })

    def test_rejects_invalid_limit(self):
        """Malformed: limit out of range is rejected."""
        with pytest.raises(TraceQueryError, match="'limit' must be an integer"):
            TraceQueryService.parse_and_validate_query({
                "trace_type": "test",
                "limit": -1,
            })

    def test_rejects_limit_too_high(self):
        """Malformed: limit exceeding max is rejected."""
        with pytest.raises(TraceQueryError, match="'limit' must be an integer"):
            TraceQueryService.parse_and_validate_query({
                "trace_type": "test",
                "limit": 99999,
            })

    def test_valid_with_optional_params(self):
        """Authorized: all optional params accepted."""
        result = TraceQueryService.parse_and_validate_query({
            "trace_type": "agent_execution",
            "filters": {"status": "running"},
            "limit": 50,
            "offset": 10,
            "sort": "timestamp",
        })
        assert result["limit"] == 50
        assert result["offset"] == 10
        assert result["sort"] == "timestamp"

    def test_deeply_nested_and_or_chain(self):
        """Unauthorized: deeply nested $and/$or chains rejected."""
        filters = {}
        current = filters
        for i in range(MAX_FILTER_DEPTH + 1):
            child = {f"field_{i}": f"val_{i}"}
            current["$or"] = [child]
            current = child

        with pytest.raises(NestedFilterDepthError):
            TraceQueryService.parse_and_validate_query({
                "trace_type": "agent_execution",
                "filters": filters,
            })

    def test_rejects_excessive_not_depth(self):
        """Unauthorized: deeply nested $not chains rejected."""
        filters = {}
        current = filters
        for i in range(MAX_FILTER_DEPTH + 1):
            child = {f"field_{i}": f"val_{i}"}
            current["$not"] = child
            current = child

        with pytest.raises(NestedFilterDepthError):
            TraceQueryService.parse_and_validate_query({
                "trace_type": "agent_execution",
                "filters": filters,
            })


class TestTraceQueryAPI:
    """Integration tests for the trace query API endpoint."""

    @pytest.fixture(autouse=True)
    def _auth_header(self):
        self.auth_header = {"Authorization": "Bearer test-token"}

    def test_trace_query_authorized_request(self, client):
        """Authorized: valid request returns 200 with results."""
        response = client.post(
            "/api/v2/traces/query",
            json={
                "trace_type": "agent_execution",
                "filters": {"status": "completed"},
                "limit": 10,
            },
            headers=self.auth_header,
        )
        assert response.status_code == 200
        data = response.json()
        assert "traces" in data
        assert "total" in data

    def test_trace_query_unauthorized_no_token(self, client):
        """Unauthorized: missing auth token returns 401."""
        response = client.post(
            "/api/v2/traces/query",
            json={
                "trace_type": "agent_execution",
                "filters": {"status": "completed"},
            },
        )
        assert response.status_code == 401
        assert "Unauthorized" in response.text

    def test_trace_query_malformed_body(self, client):
        """Malformed: invalid request body returns 422."""
        response = client.post(
            "/api/v2/traces/query",
            json={"not_trace_type": "test"},
            headers=self.auth_header,
        )
        assert response.status_code == 422

    def test_trace_query_excessive_nested_filters(self, client):
        """Malformed: overly nested filters return 422."""
        filters = {}
        current = filters
        for i in range(MAX_FILTER_DEPTH + 2):
            child = {f"field_{i}": f"val_{i}"}
            current["$and"] = [child]
            current = child

        response = client.post(
            "/api/v2/traces/query",
            json={
                "trace_type": "agent_execution",
                "filters": filters,
            },
            headers=self.auth_header,
        )
        assert response.status_code == 422

    def test_trace_query_invalid_limit(self, client):
        """Malformed: invalid limit returns 422."""
        response = client.post(
            "/api/v2/traces/query",
            json={
                "trace_type": "agent_execution",
                "filters": {},
                "limit": 99999,
            },
            headers=self.auth_header,
        )
        assert response.status_code == 422

    def test_trace_query_health_endpoint(self, client):
        """Health check endpoint works."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
