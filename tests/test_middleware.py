"""Tests for upload boundary validation middleware."""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api.middleware import (
    UploadBoundaryMiddleware,
    _extract_boundary,
    _validate_boundary,
)


# Helper: simple endpoint
async def ok_endpoint(request):
    return PlainTextResponse("uploaded")


def _make_client():
    app = Starlette(routes=[Route("/upload", ok_endpoint, methods=["POST"])])
    app.add_middleware(UploadBoundaryMiddleware)
    return TestClient(app)


class TestBoundaryExtraction:
    def test_extract_valid_boundary(self):
        b = _extract_boundary('multipart/form-data; boundary=----WebKitFormBoundary')
        assert b == '----WebKitFormBoundary'

    def test_extract_quoted_boundary(self):
        b = _extract_boundary('multipart/form-data; boundary="abc123"')
        assert b == 'abc123'

    def test_extract_no_boundary(self):
        b = _extract_boundary('multipart/form-data')
        assert b is None

    def test_extract_wrong_content_type(self):
        b = _extract_boundary('application/json')
        assert b is None

    def test_extract_none_header(self):
        b = _extract_boundary(None)
        assert b is None

    def test_extract_empty_header(self):
        b = _extract_boundary('')
        assert b is None

    def test_extract_multipart_mixed(self):
        b = _extract_boundary('multipart/mixed; boundary=xyz_123')
        assert b == 'xyz_123'


class TestBoundaryValidation:
    def test_valid_simple_boundary(self):
        assert _validate_boundary("----WebKitFormBoundaryABC123") is None

    def test_valid_boundary_with_special_chars(self):
        assert _validate_boundary("---=_Part_0+1(2),3.4:5?/6") is None

    def test_rejects_missing_boundary(self):
        assert _validate_boundary(None) is not None

    def test_rejects_empty_boundary(self):
        assert _validate_boundary("") is not None

    def test_rejects_whitespace_in_boundary(self):
        err = _validate_boundary("boundary with spaces")
        assert err is not None

    def test_rejects_too_long_boundary(self):
        err = _validate_boundary("a" * 71)
        assert err is not None
        assert "too long" in err.lower()

    def test_accepts_max_length_boundary(self):
        assert _validate_boundary("a" * 70) is None


class TestUploadBoundaryMiddleware:
    def test_rejects_missing_boundary_multipart(self):
        client = _make_client()
        resp = client.post(
            "/upload",
            content=b"some content",
            headers={"Content-Type": "multipart/form-data"},
        )
        assert resp.status_code == 400
        assert resp.headers.get("X-Upload-Error") == "invalid-boundary"

    def test_rejects_invalid_boundary_chars(self):
        client = _make_client()
        resp = client.post(
            "/upload",
            content=b"some content",
            headers={"Content-Type": 'multipart/form-data; boundary=has spaces!'},
        )
        assert resp.status_code == 400
        assert resp.headers.get("X-Upload-Error") == "invalid-boundary"

    def test_rejects_overlong_boundary(self):
        client = _make_client()
        resp = client.post(
            "/upload",
            content=b"some content",
            headers={"Content-Type": f'multipart/form-data; boundary={"a" * 71}'},
        )
        assert resp.status_code == 400

    def test_accepts_valid_boundary(self):
        client = _make_client()
        resp = client.post(
            "/upload",
            content=b"some content",
            headers={"Content-Type": "multipart/form-data; boundary=----WebKitFormBoundary"},
        )
        assert resp.status_code == 200
        assert resp.text == "uploaded"

    def test_accepts_non_multipart_request(self):
        client = _make_client()
        resp = client.post(
            "/upload",
            content=b'{"key": "value"}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    def test_rejects_oversized_payload(self):
        client = _make_client()
        large_body = b"x" * (100 * 1024 * 1024 + 1)
        resp = client.post(
            "/upload",
            content=large_body,
            headers={
                "Content-Type": "multipart/form-data; boundary=validBoundary",
                "Content-Length": str(len(large_body)),
            },
        )
        assert resp.status_code == 413

    def test_multipart_accept_under_max_size(self):
        client = _make_client()
        body = b"x" * (50 * 1024 * 1024)
        # Note: using raw bytes to avoid starlette multipart parsing
        resp = client.post(
            "/upload",
            content=body,
            headers={
                "Content-Type": "multipart/form-data; boundary=----WebKitFormBoundary",
                "Content-Length": str(len(body)),
            },
        )
        assert resp.status_code == 200

    def test_valid_boundary_with_special_rfc2046_chars(self):
        client = _make_client()
        special = "---=_NextPart_001_01DA+()',./:?="
        resp = client.post(
            "/upload",
            content=b"some content",
            headers={"Content-Type": f"multipart/form-data; boundary={special}"},
        )
        assert resp.status_code == 200

    def test_x_upload_error_header_on_rejection(self):
        client = _make_client()
        resp = client.post(
            "/upload",
            content=b"x",
            headers={"Content-Type": "multipart/form-data"},
        )
        assert resp.headers.get("X-Upload-Error") == "invalid-boundary"

# 2026-05-19T12:00:00 test update
