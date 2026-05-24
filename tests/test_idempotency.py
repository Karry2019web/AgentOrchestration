"""Tests for the task creation endpoint with cross-user idempotency key enforcement."""

import pytest
from fastapi.testclient import TestClient
from src.api.server import create_app
from src.api.routes import idempotency_registry, _idempotency_results
from src.agent.registry import AgentRegistry


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_registries():
    """Reset global state between tests."""
    idempotency_registry._store.clear()
    _idempotency_results.clear()


@pytest.fixture
def registered_agent():
    """Register an agent and return its ID."""
    registry = AgentRegistry()
    return registry.register("test-worker", "worker.processor")


class TestTaskCreationIdempotency:
    """Regression tests for the Reject duplicate idempotency keys across users condition."""

    def test_create_task_with_idempotency_key(self, client, registered_agent):
        """Verified: creating a task with a valid idempotency key succeeds."""
        response = client.post(
            "/api/v2/tasks",
            json={
                "idempotency_key": "unique-key-001",
                "agent_id": registered_agent,
                "type": "data.process",
                "payload": {"file": "input.csv"},
            },
            headers={"Authorization": "Bearer user-a-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert "task_id" in data
        assert data["agent_id"] == registered_agent

    def test_idempotent_replay_same_user(self, client, registered_agent):
        """Verified: retrying with the same key and same user returns the same result (idempotent)."""
        body = {
            "idempotency_key": "replay-key-002",
            "agent_id": registered_agent,
            "type": "data.process",
            "payload": {"file": "input.csv"},
        }
        resp1 = client.post(
            "/api/v2/tasks",
            json=body,
            headers={"Authorization": "Bearer user-a-token"},
        )
        assert resp1.status_code == 200
        result1 = resp1.json()

        resp2 = client.post(
            "/api/v2/tasks",
            json=body,
            headers={"Authorization": "Bearer user-a-token"},
        )
        assert resp2.status_code == 200
        result2 = resp2.json()
        assert result2 == result1

    def test_reject_different_user_same_key(self, client, registered_agent):
        """Verified: a different user cannot reuse the same idempotency key (cross-user rejection)."""
        body = {
            "idempotency_key": "cross-user-key-003",
            "agent_id": registered_agent,
            "type": "data.process",
            "payload": {"file": "input.csv"},
        }
        resp1 = client.post(
            "/api/v2/tasks",
            json=body,
            headers={"Authorization": "Bearer user-a-token"},
        )
        assert resp1.status_code == 200

        resp2 = client.post(
            "/api/v2/tasks",
            json=body,
            headers={"Authorization": "Bearer user-b-token"},
        )
        assert resp2.status_code == 409
        data = resp2.json()
        assert "different user" in data["detail"].lower()

    def test_reject_missing_idempotency_key(self, client, registered_agent):
        """Verified: a request without an idempotency key returns 400."""
        response = client.post(
            "/api/v2/tasks",
            json={
                "agent_id": registered_agent,
                "type": "data.process",
            },
            headers={"Authorization": "Bearer user-a-token"},
        )
        assert response.status_code == 400

    def test_reject_missing_agent_id(self, client):
        """Verified: a request without an agent_id returns 400."""
        response = client.post(
            "/api/v2/tasks",
            json={
                "idempotency_key": "missing-agent-004",
                "type": "data.process",
            },
            headers={"Authorization": "Bearer user-a-token"},
        )
        assert response.status_code == 400

    def test_reject_nonexistent_agent(self, client):
        """Verified: a request referencing a non-existent agent returns 404."""
        response = client.post(
            "/api/v2/tasks",
            json={
                "idempotency_key": "bad-agent-005",
                "agent_id": "nonexistent-id",
                "type": "data.process",
            },
            headers={"Authorization": "Bearer user-a-token"},
        )
        assert response.status_code == 404

    def test_unauthorized_request(self, client, registered_agent):
        """Verified: a request without an Authorization header returns 401."""
        response = client.post(
            "/api/v2/tasks",
            json={
                "idempotency_key": "unauth-key-006",
                "agent_id": registered_agent,
                "type": "data.process",
            },
            headers={},
        )
        assert response.status_code == 401

    def test_malformed_payload(self, client, registered_agent):
        """Verified: malformed payloads (non-dict) are still validated."""
        response = client.post(
            "/api/v2/tasks",
            json="not-a-dict",
            headers={"Authorization": "Bearer user-a-token"},
        )
        assert response.status_code in (400, 422)
