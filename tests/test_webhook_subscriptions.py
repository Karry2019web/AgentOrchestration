"""Tests for webhook subscription API."""
import pytest
from fastapi.testclient import TestClient
from src.api.server import create_app


class TestWebhookSubscriptions:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(create_app())

    def test_create_subscription_valid_event_types(self):
        response = self.client.post(
            "/api/v2/webhook/subscriptions",
            json={
                "url": "https://hooks.example.com/events",
                "event_types": ["agent.created", "run.completed"],
                "description": "Test subscription",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://hooks.example.com/events"
        assert data["event_types"] == ["agent.created", "run.completed"]
        assert data["active"] is True
        assert data["description"] == "Test subscription"

    def test_create_subscription_invalid_event_type_raises_400(self):
        response = self.client.post(
            "/api/v2/webhook/subscriptions",
            json={
                "url": "https://hooks.example.com/events",
                "event_types": ["invalid.event", "run.completed"],
            },
        )
        assert response.status_code == 400
        assert "invalid.event" in response.json()["detail"]

    def test_create_subscription_all_invalid_types_raises_400(self):
        response = self.client.post(
            "/api/v2/webhook/subscriptions",
            json={
                "url": "https://hooks.example.com/events",
                "event_types": ["foo.bar", "baz.qux"],
            },
        )
        assert response.status_code == 400

    def test_list_subscriptions(self):
        self.client.post(
            "/api/v2/webhook/subscriptions",
            json={"url": "https://h1.example.com/ev", "event_types": ["agent.created"]},
        )
        self.client.post(
            "/api/v2/webhook/subscriptions",
            json={"url": "https://h2.example.com/ev", "event_types": ["run.completed"]},
        )
        response = self.client.get("/api/v2/webhook/subscriptions")
        assert response.status_code == 200
        data = response.json()
        assert len(data["subscriptions"]) == 2

    def test_get_subscription_by_id(self):
        create_resp = self.client.post(
            "/api/v2/webhook/subscriptions",
            json={"url": "https://h.example.com/ev", "event_types": ["agent.created"]},
        )
        sub_id = create_resp.json()["id"]
        get_resp = self.client.get(f"/api/v2/webhook/subscriptions/{sub_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == sub_id

    def test_get_nonexistent_subscription_returns_404(self):
        response = self.client.get("/api/v2/webhook/subscriptions/nonexistent-id")
        assert response.status_code == 404

    def test_delete_subscription(self):
        create_resp = self.client.post(
            "/api/v2/webhook/subscriptions",
            json={"url": "https://h.example.com/ev", "event_types": ["agent.created"]},
        )
        sub_id = create_resp.json()["id"]
        del_resp = self.client.delete(f"/api/v2/webhook/subscriptions/{sub_id}")
        assert del_resp.status_code == 200
        get_resp = self.client.get(f"/api/v2/webhook/subscriptions/{sub_id}")
        assert get_resp.status_code == 404

    def test_toggle_subscription_active_state(self):
        create_resp = self.client.post(
            "/api/v2/webhook/subscriptions",
            json={"url": "https://h.example.com/ev", "event_types": ["agent.created"]},
        )
        sub_id = create_resp.json()["id"]
        assert create_resp.json()["active"] is True

        toggle_resp = self.client.patch(f"/api/v2/webhook/subscriptions/{sub_id}/toggle")
        assert toggle_resp.status_code == 200
        assert toggle_resp.json()["active"] is False

        toggle_resp2 = self.client.patch(f"/api/v2/webhook/subscriptions/{sub_id}/toggle")
        assert toggle_resp2.status_code == 200
        assert toggle_resp2.json()["active"] is True
