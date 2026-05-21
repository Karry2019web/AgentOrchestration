"""Tests for hold-aware artifact retention deletion."""

import time
import pytest
from src.artifacts.retention import ArtifactRetention, HoldType


class TestArtifactRetention:
    """Test hold-aware artifact retention."""

    def setup_method(self):
        self.retention = ArtifactRetention()

    def test_store_and_get_artifact(self):
        self.retention.store_artifact("art-1", "data-1", retention_days=30)
        art = self.retention.get_artifact("art-1")
        assert art is not None
        assert art["id"] == "art-1"
        assert art["data"] == "data-1"
        assert art["retention_days"] == 30

    def test_apply_hold(self):
        self.retention.store_artifact("art-1", "data-1")
        assert self.retention.apply_hold("art-1", HoldType.LEGAL, "Active litigation")
        assert self.retention.is_held("art-1") is True

    def test_apply_hold_nonexistent_artifact(self):
        assert self.retention.apply_hold("nonexistent", HoldType.LEGAL, "reason") is False

    def test_remove_hold(self):
        self.retention.store_artifact("art-1", "data-1")
        self.retention.apply_hold("art-1", HoldType.LEGAL, "Active litigation")
        assert self.retention.remove_hold("art-1") is True
        assert self.retention.is_held("art-1") is False

    def test_delete_expired_skips_held_artifacts(self):
        """Held expired artifacts should NOT be deleted."""
        # Store with 0 retention days so it's immediately expired
        self.retention.store_artifact("art-1", "data-1", retention_days=-1)
        self.retention.apply_hold("art-1", HoldType.LEGAL, "Audit hold")

        report = self.retention.delete_expired()
        assert report["deleted_count"] == 0
        assert report["held_skipped_count"] == 1
        assert report["held_skipped"][0]["artifact_id"] == "art-1"
        # Artifact should still exist
        assert self.retention.get_artifact("art-1") is not None

    def test_delete_expired_removes_non_held(self):
        """Non-held expired artifacts should be deleted."""
        self.retention.store_artifact("art-1", "data-1", retention_days=-1)

        report = self.retention.delete_expired()
        assert report["deleted_count"] == 1
        assert report["held_skipped_count"] == 0
        assert self.retention.get_artifact("art-1") is None

    def test_mixed_held_and_non_held(self):
        """Mix of held and non-held expired artifacts."""
        self.retention.store_artifact("art-1", "data-1", retention_days=-1)
        self.retention.store_artifact("art-2", "data-2", retention_days=-1)
        self.retention.apply_hold("art-2", HoldType.INVESTIGATION, "Security investigation")

        report = self.retention.delete_expired()
        assert report["deleted_count"] == 1  # art-1 deleted
        assert report["held_skipped_count"] == 1  # art-2 held
        assert self.retention.get_artifact("art-1") is None
        assert self.retention.get_artifact("art-2") is not None

    def test_non_expired_artifacts_untouched(self):
        """Non-expired artifacts should never be deleted by cleanup."""
        self.retention.store_artifact("art-1", "data-1", retention_days=365)
        self.retention.store_artifact("art-2", "data-2", retention_days=-1)

        report = self.retention.delete_expired()
        assert report["deleted_count"] == 1  # only art-2 expired
        assert self.retention.get_artifact("art-1") is not None  # still there

    def test_all_hold_types(self):
        """All hold types should prevent deletion."""
        self.retention.store_artifact("art-1", "data-1", retention_days=-1)
        self.retention.store_artifact("art-2", "data-2", retention_days=-1)
        self.retention.store_artifact("art-3", "data-3", retention_days=-1)

        self.retention.apply_hold("art-1", HoldType.LEGAL, "Legal hold")
        self.retention.apply_hold("art-2", HoldType.INVESTIGATION, "Investigation")
        self.retention.apply_hold("art-3", HoldType.COMPLIANCE, "Compliance hold")

        report = self.retention.delete_expired()
        assert report["deleted_count"] == 0
        assert report["held_skipped_count"] == 3

    def test_hold_removal_allows_deletion(self):
        """Removing a hold should allow the artifact to be deleted."""
        self.retention.store_artifact("art-1", "data-1", retention_days=-1)
        self.retention.apply_hold("art-1", HoldType.LEGAL, "Legal hold")
        self.retention.remove_hold("art-1")

        report = self.retention.delete_expired()
        assert report["deleted_count"] == 1

    def test_list_active_holds(self):
        self.retention.store_artifact("art-1", "data-1", retention_days=-1)
        self.retention.store_artifact("art-2", "data-2", retention_days=-1)
        self.retention.apply_hold("art-1", HoldType.LEGAL, "Legal")
        self.retention.apply_hold("art-2", HoldType.INVESTIGATION, "Investigation")
        self.retention.remove_hold("art-2")

        active = self.retention.list_holds(active_only=True)
        assert len(active) == 1
        assert active[0]["artifact_id"] == "art-1"

    def test_retention_report_includes_held_info(self):
        """Report should include hold type and reason for held artifacts."""
        self.retention.store_artifact("art-1", "data-1", retention_days=-1)
        self.retention.apply_hold("art-1", HoldType.LEGAL, "Active litigation case #42")

        report = self.retention.delete_expired()
        held = report["held_skipped"][0]
        assert held["hold_type"] == HoldType.LEGAL
        assert "litigation" in held["reason"]

    def test_count_artifacts(self):
        self.retention.store_artifact("art-1", "data-1")
        self.retention.store_artifact("art-2", "data-2")
        assert self.retention.count_artifacts() == 2

    def test_count_active_holds(self):
        self.retention.store_artifact("art-1", "data-1")
        self.retention.store_artifact("art-2", "data-2")
        self.retention.apply_hold("art-1", HoldType.LEGAL, "Legal")
        assert self.retention.count_active_holds() == 1
        self.retention.remove_hold("art-1")
        assert self.retention.count_active_holds() == 0

    def test_get_hold_info(self):
        self.retention.store_artifact("art-1", "data-1")
        self.retention.apply_hold("art-1", HoldType.COMPLIANCE, "Compliance audit", applied_by="auditor")

        info = self.retention.get_hold_info("art-1")
        assert info is not None
        assert info["hold_type"] == HoldType.COMPLIANCE
        assert info["applied_by"] == "auditor"
        assert info["active"] is True

    def test_get_hold_info_no_hold(self):
        assert self.retention.get_hold_info("nonexistent") is None

    def test_default_retention_days(self):
        self.retention.store_artifact("art-1", "data-1")
        art = self.retention.get_artifact("art-1")
        assert art["retention_days"] == 30  # default
