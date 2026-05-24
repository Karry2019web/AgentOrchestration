"""Tests for runner provenance validation."""

import os
import time
from unittest.mock import patch
import pytest

from src.ci.runner_provenance import (
    APPROVED_IMAGE_DIGESTS, MAX_IMAGE_AGE_HOURS,
    REQUIRED_RUNNER_LABELS, ENV_APPROVED_DIGESTS,
    ProvenanceReport, ProvenanceResult,
    _get_approved_digests, _get_runner_labels,
    _compute_image_digest, _is_stale_image,
    check_image_digest, check_image_freshness,
    check_runner_labels, validate,
)


class TestProvenanceResult:
    def test_to_dict(self):
        r = ProvenanceResult("test", True, "ok")
        assert r.to_dict() == {"check": "test", "passed": True, "detail": "ok"}


class TestProvenanceReport:
    def test_passed_all(self):
        r = ProvenanceReport()
        r.add(ProvenanceResult("a", True))
        r.add(ProvenanceResult("b", True))
        assert r.passed is True

    def test_failed_any(self):
        r = ProvenanceReport()
        r.add(ProvenanceResult("a", True))
        r.add(ProvenanceResult("b", False))
        assert r.passed is False

    def test_to_dict(self):
        r = ProvenanceReport()
        r.add(ProvenanceResult("x", True))
        d = r.to_dict()
        assert d["passed"] is True
        assert len(d["checks"]) == 1


class TestGetApprovedDigests:
    def test_default(self):
        d = _get_approved_digests()
        assert len(d) >= 2
        assert all(dd.startswith("sha256:") for dd in d)

    def test_env_override(self):
        os.environ[ENV_APPROVED_DIGESTS] = "sha256:test"
        try:
            assert _get_approved_digests() == ["sha256:test"]
        finally:
            del os.environ[ENV_APPROVED_DIGESTS]


class TestGetRunnerLabels:
    def test_from_env(self):
        os.environ["RUNNER_LABELS"] = "self-hosted, Linux, GPU"
        try:
            labels = _get_runner_labels()
            assert "GPU" in labels
        finally:
            del os.environ["RUNNER_LABELS"]

    @patch("src.ci.runner_provenance.sys.platform", "linux")
    @patch("src.ci.runner_provenance.platform.machine", return_value="x86_64")
    def test_fallback(self, *_):
        labels = _get_runner_labels()
        assert "Linux" in labels
        assert "x64" in labels


class TestImageDigest:
    def test_returns_string(self):
        d = _compute_image_digest()
        assert d is not None
        assert d.startswith("sha256:")

    def test_deterministic(self):
        assert _compute_image_digest() == _compute_image_digest()


class TestIsStaleImage:
    def test_fresh(self):
        assert _is_stale_image(time.time() - 3600) is False

    def test_stale(self):
        assert _is_stale_image(time.time() - (MAX_IMAGE_AGE_HOURS + 1) * 3600) is True

    def test_none(self):
        assert _is_stale_image(None) is None


class TestCheckImageDigest:
    def test_unknown_fails(self):
        report = ProvenanceReport()
        with patch("src.ci.runner_provenance._compute_image_digest", return_value="sha256:unknown"):
            check_image_digest(report)
        assert report.passed is False

    def test_known_passes(self):
        report = ProvenanceReport()
        approved = _get_approved_digests()[0]
        with patch("src.ci.runner_provenance._compute_image_digest", return_value=approved):
            check_image_digest(report)
        assert report.passed is True


class TestCheckFreshness:
    def test_fresh_passes(self):
        report = ProvenanceReport()
        with patch("src.ci.runner_provenance._get_image_build_timestamp", return_value=time.time() - 3600):
            check_image_freshness(report)
        assert report.passed is True

    def test_stale_fails(self):
        report = ProvenanceReport()
        ts = time.time() - (MAX_IMAGE_AGE_HOURS + 1) * 3600
        with patch("src.ci.runner_provenance._get_image_build_timestamp", return_value=ts):
            check_image_freshness(report)
        assert report.passed is False


class TestCheckLabels:
    def test_all_required_pass(self):
        r = ProvenanceReport()
        with patch("src.ci.runner_provenance._get_runner_labels", return_value=REQUIRED_RUNNER_LABELS):
            check_runner_labels(r)
        assert r.passed is True

    def test_missing_fails(self):
        r = ProvenanceReport()
        with patch("src.ci.runner_provenance._get_runner_labels", return_value=["Linux"]):
            check_runner_labels(r)
        assert r.passed is False

    def test_forbidden_fails(self):
        r = ProvenanceReport()
        with patch("src.ci.runner_provenance._get_runner_labels",
                   return_value=REQUIRED_RUNNER_LABELS + ["unapproved"]):
            check_runner_labels(r)
        assert r.passed is False


class TestValidate:
    def test_runs_all_checks(self):
        report = validate()
        names = {c.name for c in report.checks}
        assert names == {"image_digest", "image_freshness", "runner_labels"}

    def test_strict_does_not_crash(self):
        report = validate(strict=True)
        assert len(report.checks) == 3
