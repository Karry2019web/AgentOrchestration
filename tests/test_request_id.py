"""Tests for request ID context propagation middleware."""

import logging

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.testclient import TestClient

from src.api.middleware import RequestIDLoggingMiddleware, LoggingMiddleware
from src.api.request_id import (
    REQUEST_ID_HEADER,
    RequestIDLogFilter,
    get_request_id,
    sanitize_request_id,
)


def _app():
    """Build a test app with the middleware under test."""
    app = FastAPI()

    @app.get("/ok")
    async def ok(background_tasks: BackgroundTasks, request: Request):
        request_id = get_request_id()

        def log_background_task():
            logging.getLogger("tests.background").info("background task ran")

        background_tasks.add_task(log_background_task)
        return {
            "request_id": request_id,
            "state_request_id": request.scope.get("headers") is not None,
        }

    @app.get("/echo")
    async def echo(request: Request):
        """Echo the request ID from the header."""
        return {
            "request_id": get_request_id(),
            "header": request.headers.get(REQUEST_ID_HEADER, ""),
        }

    @app.get("/api/v2/secure")
    async def secure():
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        logging.getLogger("tests.exception").info("about to raise")
        raise RuntimeError("do not expose this")

    app.add_middleware(RequestIDLoggingMiddleware)
    app.add_middleware(LoggingMiddleware)
    return app


def _install_caplog_filter(caplog):
    """Ensure the pytest caplog handler also injects request_id."""
    caplog.handler.addFilter(RequestIDLogFilter())


class TestRequestIDPropagation:
    """Verify that X-Request-ID is enforced, propagated, and cleaned up."""

    def test_generates_request_id_when_header_missing(self):
        """When no X-Request-ID is sent, the middleware generates one."""
        response = TestClient(_app()).get("/ok")
        assert response.status_code == 200
        rid = response.headers.get(REQUEST_ID_HEADER, "")
        assert rid != ""
        assert rid != "-"
        assert " " not in rid
        assert response.json()["request_id"] == rid

    def test_reuses_valid_request_id_from_header(self):
        """A valid X-Request-ID header should be reused."""
        response = TestClient(_app()).get(
            "/ok",
            headers={REQUEST_ID_HEADER: "req-abc-123"},
        )
        assert response.status_code == 200
        assert response.headers[REQUEST_ID_HEADER] == "req-abc-123"
        assert response.json()["request_id"] == "req-abc-123"

    def test_sanitizes_invalid_request_id(self):
        """An invalid request ID is replaced with a generated one."""
        response = TestClient(_app()).get(
            "/echo",
            headers={REQUEST_ID_HEADER: "bad id with spaces and secrets!!"},
        )
        assert response.status_code == 200
        rid = response.headers[REQUEST_ID_HEADER]
        assert " " not in rid
        body = response.json()
        assert body["request_id"] == rid
        assert body["header"] == "bad id with spaces and secrets!!"

    def test_background_task_inherits_request_id(self, caplog):
        """Background tasks should log with the same request ID."""
        _install_caplog_filter(caplog)
        caplog.set_level(logging.INFO)

        response = TestClient(_app()).get(
            "/ok",
            headers={REQUEST_ID_HEADER: "req-bg-test"},
        )
        assert response.status_code == 200
        assert response.headers[REQUEST_ID_HEADER] == "req-bg-test"

        # After the response, the background task should have logged
        # with the same request ID
        background_records = [
            r for r in caplog.records if r.name == "tests.background"
        ]
        assert background_records, "Background task should have produced a log record"
        assert {r.request_id for r in background_records} == {"req-bg-test"}

    def test_context_cleared_after_request(self):
        """After the request completes, the thread-local request ID resets."""
        TestClient(_app()).get(
            "/ok",
            headers={REQUEST_ID_HEADER: "req-clear"},
        )
        # Outside a request context, the ID should be "-"
        assert get_request_id() == "-"

    def test_sanitize_request_id_valid(self):
        """sanitize_request_id should pass through valid IDs."""
        assert sanitize_request_id("abc-123._:XYZ") == "abc-123._:XYZ"

    def test_sanitize_request_id_invalid(self):
        """sanitize_request_id should replace invalid IDs."""
        result = sanitize_request_id("bad id with spaces")
        assert " " not in result
        assert len(result) == 32  # uuid4 hex

    def test_sanitize_request_id_none(self):
        """sanitize_request_id should generate an ID for None."""
        result = sanitize_request_id(None)
        assert len(result) == 32
        assert " " not in result

    def test_sanitize_request_id_empty(self):
        """sanitize_request_id should generate an ID for empty string."""
        result = sanitize_request_id("")
        assert len(result) == 32
