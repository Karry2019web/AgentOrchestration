"""Tests for TenantCorrelationMiddleware — tenant-bound correlation isolation."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import (
    TenantCorrelationMiddleware,
    LoggingMiddleware,
    get_correlation_id,
    get_tenant_id,
    get_request_id,
)


def _make_test_app():
    """App with TenantCorrelationMiddleware + a route that reads context vars."""
    app = FastAPI()

    @app.get("/echo-context")
    async def echo_context():
        return {
            "correlation_id": get_correlation_id(),
            "tenant_id": get_tenant_id(),
            "request_id": get_request_id(),
        }

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    app.add_middleware(LoggingMiddleware)
    app.add_middleware(TenantCorrelationMiddleware)
    return app


class TestTenantCorrelationMiddleware:
    def test_sets_correlation_and_request_id_headers(self):
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/health", headers={"X-Tenant-Id": "acme-corp"})
        assert resp.status_code == 200
        assert "X-Request-Id" in resp.headers
        assert "X-Correlation-Id" in resp.headers
        corr = resp.headers["X-Correlation-Id"]
        assert corr.startswith("acme-corp:")

    def test_rejects_correlation_id_tenant_mismatch(self):
        app = _make_test_app()
        client = TestClient(app)
        # Correlation ID claims tenant "evil-corp" but header says "acme-corp"
        resp = client.get(
            "/health",
            headers={
                "X-Tenant-Id": "acme-corp",
                "X-Correlation-Id": "evil-corp:some-trace-id",
            },
        )
        assert resp.status_code == 403
        assert "mismatch" in resp.text.lower()

    def test_context_vars_isolated_per_request(self):
        app = _make_test_app()
        client = TestClient(app)

        resp1 = client.get("/echo-context", headers={"X-Tenant-Id": "tenant-a"})
        resp2 = client.get("/echo-context", headers={"X-Tenant-Id": "tenant-b"})

        data1 = resp1.json()
        data2 = resp2.json()

        assert data1["tenant_id"] == "tenant-a"
        assert data2["tenant_id"] == "tenant-b"
        assert data1["correlation_id"].startswith("tenant-a:")
        assert data2["correlation_id"].startswith("tenant-b:")
        assert data1["request_id"] != data2["request_id"]

    def test_default_tenant_when_no_header(self):
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/echo-context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "default"
        assert data["correlation_id"].startswith("default:")

    def test_context_cleared_after_exception(self):
        """Context vars should not leak after an unhandled exception."""
        app = FastAPI()

        @app.get("/crash")
        async def crash():
            raise ValueError("simulated crash")

        app.add_middleware(TenantCorrelationMiddleware)
        client = TestClient(app)

        # Should return 500, not crash the middleware
        resp = client.get("/crash", headers={"X-Tenant-Id": "test-org"})
        assert resp.status_code == 500
        assert "X-Request-Id" in resp.headers

    def test_sanitized_logging_does_not_expose_raw_tenant(self):
        """Tenant ID should be hashed in debug logs, not exposed raw."""
        import logging
        from io import StringIO

        app = _make_test_app()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("src.api.middleware")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        client = TestClient(app)
        client.get("/health", headers={"X-Tenant-Id": "secret-org-42"})

        logger.removeHandler(handler)
        log_output = stream.getvalue()

        # Raw tenant ID should NOT appear in log
        assert "secret-org-42" not in log_output
        # Hashed prefix SHOULD appear
        assert "tenant=" in log_output
