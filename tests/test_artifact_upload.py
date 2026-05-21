"""Tests for artifact upload body size validation."""

import pytest
from fastapi import HTTPException

from src.api.services.artifact_service import (
    validate_artifact_size,
    DEFAULT_MAX_ARTIFACT_SIZE,
)


class TestValidateArtifactSize:
    """Tests for validate_artifact_size() shared service function."""

    def test_accepts_size_within_limit(self):
        """Content-Length under the limit should pass."""
        validate_artifact_size(1024)  # 1 KB

    def test_accepts_size_at_limit(self):
        """Content-Length exactly at the limit should pass."""
        validate_artifact_size(DEFAULT_MAX_ARTIFACT_SIZE)

    def test_rejects_size_over_limit(self):
        """Content-Length over the limit should raise 413."""
        with pytest.raises(HTTPException) as exc:
            validate_artifact_size(DEFAULT_MAX_ARTIFACT_SIZE + 1)
        assert exc.value.status_code == 413
        assert "exceeds maximum" in exc.value.detail

    def test_rejects_missing_content_length(self):
        """Missing Content-Length should raise 411."""
        with pytest.raises(HTTPException) as exc:
            validate_artifact_size(None)
        assert exc.value.status_code == 411
        assert "Content-Length header is required" in exc.value.detail

    def test_rejects_very_large_size(self):
        """A very large body should still be rejected."""
        with pytest.raises(HTTPException) as exc:
            validate_artifact_size(100 * 1024 * 1024)  # 100 MB
        assert exc.value.status_code == 413

    def test_custom_max_size(self):
        """Custom max_size should be respected."""
        with pytest.raises(HTTPException):
            validate_artifact_size(1024, max_size=512)
        validate_artifact_size(512, max_size=512)
        validate_artifact_size(256, max_size=512)
