"""Tests for the API health endpoint — execution metadata redaction."""

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app, redact_execution_metadata


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestHealthEndpoint:
    """Health endpoint regression tests covering the execution metadata redaction."""

    def test_health_returns_healthy(self, client):
        """A simple GET /health returns a 200 with status healthy."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "version" in body

    def test_health_response_omits_sensitive_keys(self, client):
        """The health response must not contain any sensitive metadata fields."""
        resp = client.get("/health")
        body = resp.json()
        sensitive = {
            "agent_registry", "scheduler_queue", "in_flight_tasks",
            "active_processes", "pid", "process_id", "hostname",
            "internal_host", "env", "environment", "secrets", "tokens",
            "api_keys", "private_ip", "config", "configuration",
            "debug", "trace_id", "span_id", "agent_id",
            "execution_id", "storage_path", "db_url", "database_url",
            "redis_url", "internal_metrics", "runtime_stats", "worker_pids",
        }
        body_keys = set(body.keys())
        leaked = body_keys & sensitive
        assert not leaked, f"Health response leaked sensitive keys: {leaked}"

    def test_health_response_is_deterministic(self, client):
        """The health response shape is stable across calls."""
        resp1 = client.get("/health")
        resp2 = client.get("/health")
        assert resp1.json() == resp2.json()

    def test_health_response_structure(self, client):
        """The health response contains only expected top-level keys."""
        resp = client.get("/health")
        body = resp.json()
        allowed_keys = {"status", "version"}
        extra = set(body.keys()) - allowed_keys
        assert not extra, f"Unexpected keys in health response: {extra}"


class TestRedactExecutionMetadata:
    """Unit tests for the redact_execution_metadata helper."""

    def test_empty_dict(self):
        assert redact_execution_metadata({}) == {}

    def test_passthrough_safe_keys(self):
        data = {"status": "healthy", "version": "2.4.1"}
        assert redact_execution_metadata(data) == data

    def test_removes_sensitive_keys(self):
        data = {"status": "healthy", "agent_registry": {"agents": 42}, "version": "2.4.1"}
        result = redact_execution_metadata(data)
        assert "agent_registry" not in result
        assert result["status"] == "healthy"

    def test_removes_nested_sensitive_keys(self):
        data = {"diagnostics": {"status": "ok", "agent_registry": {"agents": 10}}}
        result = redact_execution_metadata(data)
        assert "agent_registry" not in result["diagnostics"]

    def test_removes_sensitive_keys_from_list_items(self):
        data = {"workers": [{"id": "w1", "pid": 1234}, {"id": "w2", "pid": 5678}]}
        result = redact_execution_metadata(data)
        assert "pid" not in result["workers"][0]
        assert "pid" not in result["workers"][1]

    def test_case_insensitive_detection(self):
        data = {"Agent_Registry": "leaked", "PID": 9999}
        result = redact_execution_metadata(data)
        assert "Agent_Registry" not in result
        assert "PID" not in result

    def test_preserves_non_dict_types(self):
        assert redact_execution_metadata("string") == "string"
        assert redact_execution_metadata(42) == 42
        assert redact_execution_metadata(None) is None
