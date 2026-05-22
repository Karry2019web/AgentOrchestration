"""Tests for the storage lifecycle manager."""

import time
import pytest
from src.common.storage import (
    StorageLifecycleManager, STORAGE_CLASSES, COLD_STORAGE,
)


class TestStorageLifecycleManager:
    def setup_method(self):
        self.manager = StorageLifecycleManager()

    def test_register_artifact(self):
        self.manager.register_artifact("art-1", "standard")
        report = self.manager.get_artifact_report("art-1")
        assert report is not None
        assert report["artifact_id"] == "art-1"
        assert report["current_storage_class"] == "standard"
        assert report["transition_count"] == 0

    def test_register_unknown_class_raises(self):
        with pytest.raises(ValueError, match="Unknown storage class"):
            self.manager.register_artifact("art-2", "quantum")

    def test_record_transition(self):
        self.manager.register_artifact("art-3", "standard")
        assert self.manager.record_transition("art-3", "infrequent_access", "lifecycle")
        report = self.manager.get_artifact_report("art-3")
        assert report["current_storage_class"] == "infrequent_access"
        assert report["transition_count"] == 1

    def test_record_transition_nonexistent(self):
        assert not self.manager.record_transition("nonexistent", "archive")

    def test_cold_storage_detection(self):
        self.manager.register_artifact("art-hot", "standard")
        self.manager.register_artifact("art-cold", "archive")
        cold = self.manager.list_cold_storage_artifacts()
        cold_ids = [c["artifact_id"] for c in cold]
        assert "art-cold" in cold_ids
        assert "art-hot" not in cold_ids

    def test_retrieval_estimate(self):
        self.manager.register_artifact("art-4", "deep_archive")
        report = self.manager.get_artifact_report("art-4")
        assert report["retrieval_estimate_ms"] > 0
        assert report["is_cold_storage"] is True

    def test_full_lifecycle(self):
        self.manager.register_artifact("art-5", "standard")
        self.manager.record_transition("art-5", "infrequent_access", "30_day_rule")
        self.manager.record_transition("art-5", "archive", "90_day_rule")
        report = self.manager.get_artifact_report("art-5")
        assert report["transition_count"] == 2
        assert report["current_storage_class"] == "archive"
        assert report["is_cold_storage"] is True
        assert report["retrieval_estimate_ms"] == STORAGE_CLASSES["archive"]["retrieval_ms"]

    def test_get_all_reports(self):
        self.manager.register_artifact("a1", "standard")
        self.manager.register_artifact("a2", "archive")
        reports = self.manager.get_all_reports()
        assert len(reports) == 2
