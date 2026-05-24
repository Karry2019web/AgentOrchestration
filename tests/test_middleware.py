"""Tests for API middleware components."""

import json
import logging

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api.middleware import (
    ValidationMiddleware,
    LoggingMiddleware,
    current_request_id,
)


def _make_app():
    async def ok_handler(request):
        return JSONResponse({"status": "ok"})

    async def error_handler(request):
        raise ValueError("handler error")

    routes = [
        Route("/api/v2/agents", endpoint=ok_handler, methods=["GET"]),
        Route("/api/v2/agents/test-123", endpoint=ok_handler, methods=["GET"]),
        Route("/api/v2/agents/test-123/start", endpoint=ok_handler, methods=["POST"]),
        Route("/health", endpoint=ok_handler, methods=["GET"]),
        Route("/error-path", endpoint=error_handler, methods=["GET"]),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(ValidationMiddleware)
    app.add_middleware(LoggingMiddleware)
    return app


def test_valid_request_passes():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v2/agents")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") is not None
    assert resp.headers.get("X-Validation-Result") == "accepted"


def test_invalid_path_rejected():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v2/agents/../../etc")
    assert resp.status_code == 400
    assert resp.headers.get("X-Validation-Result") == "rejected"
    body = resp.json()
    assert "error" in body
    assert body.get("request_id") is not None


def test_malformed_agent_id_rejected():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v2/agents/<script>")
    assert resp.status_code == 400
    assert resp.headers.get("X-Validation-Result") == "rejected"


def test_unsupported_content_type_rejected():
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v2/agents/test-123/start",
        content="some plain text",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 415
    assert resp.headers.get("X-Validation-Result") == "rejected"


def test_health_and_docs_skip_validation():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_logging_middleware_adds_duration_header():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v2/agents")
    assert resp.status_code == 200
    assert resp.headers.get("X-Duration-Ms") is not None
    duration = float(resp.headers["X-Duration-Ms"])
    assert duration >= 0


def test_request_id_propagated_on_validation_rejection():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v2/agents/%00")
    assert resp.status_code == 400
    assert resp.headers.get("X-Request-ID") is not None


def test_contextvar_cleared_in_finally():
    app = _make_app()
    client = TestClient(app)

    assert current_request_id.get() is None

    resp = client.get("/api/v2/agents")
    assert resp.status_code == 200
    assert current_request_id.get() is None

    resp = client.get("/api/v2/agents/test-456")
    assert resp.status_code == 200
    assert current_request_id.get() is None


def test_middleware_handles_exception():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/error-path")
    assert resp.status_code == 500
    assert resp.headers.get("X-Validation-Result") == "error"
