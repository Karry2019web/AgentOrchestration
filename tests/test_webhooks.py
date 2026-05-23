"""Tests for webhook subscription filter validation."""

from fastapi.testclient import TestClient
from src.api.server import create_app
from src.api.webhooks import webhooks


def setup_function():
    webhooks.clear()


def client():
    return TestClient(create_app())


headers = {"Authorization": "Bearer test-token"}


def test_create_webhook_subscription_with_valid_filters():
    http = client()
    response = http.post(
        "/api/v2/webhooks/subscriptions",
        json={
            "target_url": "https://hooks.example.com/events",
            "filters": {"event_type": "task.completed", "workspace_id": "ws-1"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["target_url"] == "https://hooks.example.com/events"
    assert data["filters"]["event_type"] == "task.completed"


def test_create_webhook_subscription_rejects_invalid_filter_fields():
    http = client()
    response = http.post(
        "/api/v2/webhooks/subscriptions",
        json={
            "target_url": "https://hooks.example.com/events",
            "filters": {"not_allowed_field": "value", "event_type": "task.completed"},
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert "not_allowed_field" in response.json()["detail"]


def test_create_webhook_subscription_rejects_http_target_url():
    http = client()
    response = http.post(
        "/api/v2/webhooks/subscriptions",
        json={
            "target_url": "http://insecure.example.com/events",
            "filters": {"event_type": "task.completed"},
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "https" in response.json()["detail"]


def test_disable_webhook_subscription():
    http = client()
    create_resp = http.post(
        "/api/v2/webhooks/subscriptions",
        json={"target_url": "https://hooks.example.com/events", "filters": {}},
        headers=headers,
    )
    assert create_resp.status_code == 200
    sub_id = create_resp.json()["subscription_id"]

    disable_resp = http.post(
        f"/api/v2/webhooks/subscriptions/{sub_id}/disable",
        headers=headers,
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["enabled"] is False


def test_disable_nonexistent_webhook_subscription():
    http = client()
    response = http.post(
        "/api/v2/webhooks/subscriptions/nonexistent-id/disable",
        headers=headers,
    )
    assert response.status_code == 404


def test_matches_filters_matches_correctly():
    sub = webhooks.create_subscription(
        workspace_id="default",
        target_url="https://hooks.example.com/events",
        filters={"event_type": "task.completed"},
    )
    event = {"event_type": "task.completed", "agent_id": "a1"}
    assert webhooks.matches_filters(sub, event)


def test_matches_filters_rejects_non_matching():
    sub = webhooks.create_subscription(
        workspace_id="default",
        target_url="https://hooks.example.com/events",
        filters={"event_type": "task.failed"},
    )
    event = {"event_type": "task.completed"}
    assert not webhooks.matches_filters(sub, event)


def test_matches_filters_empty_filters_matches_all():
    sub = webhooks.create_subscription(
        workspace_id="default",
        target_url="https://hooks.example.com/events",
        filters={},
    )
    assert webhooks.matches_filters(sub, {})
    assert webhooks.matches_filters(sub, {"event_type": "anything"})
