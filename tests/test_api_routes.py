"""Tests for request size limiting and artifact upload."""

import os
import json
from fastapi.testclient import TestClient
from src.api.server import create_app

app = create_app()
client = TestClient(app)


class TestRequestSizeLimitMiddleware:
    def test_normal_request_passes(self):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_missing_content_length_on_post_returns_411(self):
        resp = client.post("/api/v2/agents/count")
        assert resp.status_code == 411

    def test_invalid_content_length_returns_400(self):
        resp = client.post(
            "/api/v2/agents/count",
            headers={"Content-Length": "abc", "Authorization": "Bearer test"},
            content=b"test"
        )
        assert resp.status_code == 400

    def test_negative_content_length_returns_411(self):
        resp = client.post(
            "/api/v2/agents/count",
            headers={"Content-Length": "-5", "Authorization": "Bearer test"},
            content=b"test"
        )
        assert resp.status_code == 411

    def test_oversized_body_returns_413(self):
        big_body = b"x" * (11 * 1024 * 1024)
        resp = client.post(
            "/api/v2/agents/count",
            headers={"Content-Length": str(len(big_body)), "Authorization": "Bearer test"},
            content=big_body
        )
        assert resp.status_code == 413

    def test_get_without_content_length_ok(self):
        resp = client.get("/api/v2/agents")
        assert resp.status_code == 200


class TestArtifactUpload:
    def test_upload_valid_file(self):
        resp = client.post(
            "/api/v2/artifacts/upload",
            files={"file": ("test.txt", b"hello world", "text/plain")}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "test.txt"
        assert data["size"] == 11
        assert "artifact_id" in data

    def test_upload_empty_filename_returns_400(self):
        resp = client.post(
            "/api/v2/artifacts/upload",
            files={"file": ("", b"content", "text/plain")}
        )
        assert resp.status_code == 400

    def test_upload_oversized_artifact_returns_413(self):
        big = b"x" * (60 * 1024 * 1024)
        resp = client.post(
            "/api/v2/artifacts/upload",
            files={"file": ("big.bin", big, "application/octet-stream")}
        )
        assert resp.status_code == 413

    def test_upload_no_file_returns_422(self):
        resp = client.post("/api/v2/artifacts/upload")
        assert resp.status_code == 422
