"""Tests for MultipartBoundaryMiddleware."""

import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import MultipartBoundaryMiddleware


class TestMultipartBoundaryMiddleware:
    """Test suite for MultipartBoundaryMiddleware."""

    def setup_method(self):
        self.middleware = MultipartBoundaryMiddleware(app=None)

    # --- _extract_boundary ---

    def test_extract_boundary_simple(self):
        ct = "multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW"
        assert self.middleware._extract_boundary(ct) == "----WebKitFormBoundary7MA4YWxkTrZu0gW"

    def test_extract_boundary_quoted(self):
        ct = 'multipart/form-data; boundary="----WebKitFormBoundary7MA4YWxkTrZu0gW"'
        assert self.middleware._extract_boundary(ct) == "----WebKitFormBoundary7MA4YWxkTrZu0gW"

    def test_extract_boundary_no_boundary(self):
        ct = "multipart/form-data"
        assert self.middleware._extract_boundary(ct) is None

    def test_extract_boundary_empty_value(self):
        ct = "multipart/form-data; boundary="
        assert self.middleware._extract_boundary(ct) == ""

    def test_extract_boundary_extra_params(self):
        ct = "multipart/form-data; boundary=abc123; charset=utf-8"
        assert self.middleware._extract_boundary(ct) == "abc123"

    def test_extract_boundary_not_multipart(self):
        ct = "application/json"
        assert self.middleware._extract_boundary(ct) is None

    # --- _validate_boundary ---

    def test_validate_boundary_valid(self):
        assert self.middleware._validate_boundary("----WebKitFormBoundary7MA4YWxkTrZu0gW") is None

    def test_validate_boundary_simple(self):
        assert self.middleware._validate_boundary("abc123") is None

    def test_validate_boundary_with_hyphen_dot_underscore(self):
        assert self.middleware._validate_boundary("boundary-1._2+3/4") is None

    def test_validate_boundary_none(self):
        err = self.middleware._validate_boundary(None)
        assert err is not None
        assert "Missing" in err

    def test_validate_boundary_blank(self):
        err = self.middleware._validate_boundary("")
        assert err is not None
        assert "Blank" in err

    def test_validate_boundary_too_long(self):
        long_boundary = "x" * 100
        err = self.middleware._validate_boundary(long_boundary)
        assert err is not None
        assert "too long" in err.lower()

    def test_validate_boundary_starts_with_invalid_char(self):
        err = self.middleware._validate_boundary("-abc")
        assert err is not None
        assert "Malformed" in err

    def test_validate_boundary_with_special_chars(self):
        err = self.middleware._validate_boundary("abc def")
        assert err is not None
        assert "Malformed" in err

    def test_validate_boundary_exact_max_length(self):
        boundary = "x" * 70
        assert self.middleware._validate_boundary(boundary) is None

    def test_validate_boundary_one_over_max(self):
        boundary = "x" * 71
        err = self.middleware._validate_boundary(boundary)
        assert err is not None

    # --- _extract_boundary integration with _validate_boundary ---

    def test_full_validation_chain_valid(self):
        ct = "multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW"
        boundary = self.middleware._extract_boundary(ct)
        assert self.middleware._validate_boundary(boundary) is None

    def test_full_validation_chain_no_boundary(self):
        ct = "multipart/form-data"
        boundary = self.middleware._extract_boundary(ct)
        assert self.middleware._validate_boundary(boundary) is not None

    def test_full_validation_chain_blank_boundary(self):
        ct = "multipart/form-data; boundary="
        boundary = self.middleware._extract_boundary(ct)
        err = self.middleware._validate_boundary(boundary)
        assert err is not None
        assert "Blank" in err

    def test_non_multipart_passthrough(self):
        ct = "application/json"
        boundary = self.middleware._extract_boundary(ct)
        assert boundary is None
