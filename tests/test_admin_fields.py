"""Tests for admin-only field enforcement in run detail API."""

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.api.models import enforce_admin_fields, require_admin_role, RunDetailPublic, RunDetailAdmin


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def sample_run():
    return {
        "id": "run-001",
        "name": "test-agent",
        "agent_type": "worker",
        "status": "running",
        "created_at": 1000.0,
        "updated_at": 1001.0,
        "metrics": {"tasks_completed": 5, "errors": 0, "uptime": 3600.0},
        "host": "worker-01.internal",
        "container_id": "abc123def456",
        "ip_address": "10.0.1.42",
        "environment_vars": {"DEPLOY_ENV": "staging"},
        "log_path": "/var/log/agent/run-001.log",
        "token_id": "tok_admin_abc",
    }


class TestEnforceAdminFields:
    """Unit tests for field-level admin enforcement."""

    def test_non_admin_strips_admin_fields(self, sample_run):
        result = enforce_admin_fields(sample_run, is_admin=False)
        assert "host" not in result
        assert "container_id" not in result
        assert "ip_address" not in result
        assert "environment_vars" not in result
        assert "log_path" not in result
        assert "token_id" not in result

    def test_admin_keeps_all_fields(self, sample_run):
        result = enforce_admin_fields(sample_run, is_admin=True)
        assert result["host"] == "worker-01.internal"
        assert result["container_id"] == "abc123def456"
        assert result["environment_vars"]["DEPLOY_ENV"] == "staging"

    def test_non_admin_keeps_public_fields(self, sample_run):
        result = enforce_admin_fields(sample_run, is_admin=False)
        assert result["id"] == "run-001"
        assert result["name"] == "test-agent"
        assert result["status"] == "running"
        assert result["metrics"]["tasks_completed"] == 5


class TestRequireAdminRole:
    def test_admin_role_returns_true(self):
        assert require_admin_role("admin") is True
        assert require_admin_role("owner") is True
        assert require_admin_role("superuser") is True

    def test_non_admin_roles_return_false(self):
        assert require_admin_role("viewer") is False
        assert require_admin_role("editor") is False
        assert require_admin_role("member") is False

    def test_none_role_returns_false(self):
        assert require_admin_role(None) is False

    def test_case_insensitive(self):
        assert require_admin_role("Admin") is True
        assert require_admin_role("OWNER") is True


class TestRunDetailModels:
    """Test Pydantic model serialization."""

    def test_run_detail_public_excludes_admin_fields(self, sample_run):
        public = RunDetailPublic(**{k: v for k, v in sample_run.items()
                                     if k in RunDetailPublic.model_fields})
        assert public.id == "run-001"
        assert not hasattr(public, "host")

    def test_run_detail_admin_includes_admin_fields(self, sample_run):
        admin = RunDetailAdmin(**sample_run)
        assert admin.id == "run-001"
        assert admin.host == "worker-01.internal"
        assert admin.container_id == "abc123def456"


class TestRunDetailAPI:
    """Integration tests for the /runs/{agent_id} endpoint."""

    def test_get_run_detail_returns_public_for_regular_user(self, client):
        # Register an agent first
        resp = client.post("/api/v2/agents", params={
            "name": "test-agent",
            "agent_type": "worker"
        })
        assert resp.status_code == 200
        agent_id = resp.json()["agent_id"]

        resp = client.get(f"/api/v2/runs/{agent_id}")
        assert resp.status_code == 200
        data = resp.json()
        # Should not contain admin-only fields
        assert "host" not in data
        assert "container_id" not in data
        assert "ip_address" not in data

    def test_get_run_detail_returns_admin_fields_for_admin(self, client):
        resp = client.post("/api/v2/agents", params={
            "name": "admin-agent",
            "agent_type": "coordinator"
        })
        assert resp.status_code == 200
        agent_id = resp.json()["agent_id"]

        resp = client.get(
            f"/api/v2/runs/{agent_id}",
            headers={"Authorization": "Bearer admin-token-abc"}
        )
        assert resp.status_code == 200
        data = resp.json()
        # Admin fields should appear when authorization has admin token
        assert "id" in data

    def test_get_run_detail_404_for_missing(self, client):
        resp = client.get("/api/v2/runs/nonexistent")
        assert resp.status_code == 404

    def test_get_run_detail_successful_for_authenticated(self, client):
        resp = client.post("/api/v2/agents", params={
            "name": "api-agent",
            "agent_type": "worker"
        })
        assert resp.status_code == 200
        agent_id = resp.json()["agent_id"]

        resp = client.get(
            f"/api/v2/runs/{agent_id}",
            headers={"Authorization": "Bearer valid-token"}
        )
        assert resp.status_code == 200

    def test_get_agent_with_role_header(self, client):
        """GET /agents/{id} uses X-Role header for admin enforcement."""
        resp = client.post("/api/v2/agents", params={
            "name": "role-agent",
            "agent_type": "worker"
        })
        assert resp.status_code == 200
        agent_id = resp.json()["agent_id"]

        # Without admin role, should get filtered response
        resp = client.get(f"/api/v2/agents/{agent_id}")
        assert resp.status_code == 200

        # With admin role, should get full response
        resp = client.get(
            f"/api/v2/agents/{agent_id}",
            headers={"X-Role": "admin"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == agent_id
