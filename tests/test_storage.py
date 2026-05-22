"""Tests for artifact storage class tracking and lifecycle management."""

import time
import pytest
from src.storage.artifact import (
    ArtifactStorage,
    ArtifactMetadata,
    StorageClass,
    LifecycleSync,
    STORAGE_CLASS_LATENCY,
    STORAGE_CLASS_TIER,
)


class TestStorageClass:
    def test_storage_class_order(self):
        """Verify tier ordering: standard < nearline < coldline < archive."""
        assert STORAGE_CLASS_TIER == [
            StorageClass.STANDARD,
            StorageClass.NEARLINE,
            StorageClass.COLDLINE,
            StorageClass.ARCHIVE,
        ]

    def test_all_classes_have_latency(self):
        for sc in StorageClass:
            assert sc in STORAGE_CLASS_LATENCY
            assert STORAGE_CLASS_LATENCY[sc] > 0


class TestArtifactMetadata:
    def test_default_standard(self):
        meta = ArtifactMetadata(artifact_id="a1", name="test-artifact")
        assert meta.current_class == StorageClass.STANDARD
        assert not meta.is_slow_storage()

    def test_record_transition(self):
        meta = ArtifactMetadata(artifact_id="a1", name="test-artifact")
        meta.record_transition(StorageClass.COLDLINE, reason="lifecycle")
        assert meta.current_class == StorageClass.COLDLINE
        assert meta.is_slow_storage()
        assert len(meta.transitions) == 1
        assert meta.transitions[0]["from"] == "standard"
        assert meta.transitions[0]["to"] == "coldline"

    def test_retrieval_latency(self):
        meta = ArtifactMetadata(artifact_id="a1", name="test-artifact")
        assert meta.retrieval_latency_seconds() == 0.01  # STANDARD
        meta.record_transition(StorageClass.ARCHIVE)
        assert meta.retrieval_latency_seconds() == 300.0

    def test_to_dict(self):
        meta = ArtifactMetadata(artifact_id="a1", name="test-artifact")
        meta.record_transition(StorageClass.NEARLINE, reason="lifecycle")
        d = meta.to_dict()
        assert d["artifact_id"] == "a1"
        assert d["current_storage_class"] == "nearline"
        assert d["is_slow_storage"] is True
        assert d["transition_count"] == 1

    def test_from_dict(self):
        data = {
            "artifact_id": "a1",
            "name": "test",
            "current_storage_class": "coldline",
            "created_at": 1000.0,
            "updated_at": 2000.0,
            "transitions": [{"from": "standard", "to": "coldline", "timestamp": 1500.0, "reason": "lifecycle"}],
        }
        meta = ArtifactMetadata.from_dict(data)
        assert meta.artifact_id == "a1"
        assert meta.current_class == StorageClass.COLDLINE
        assert meta.is_slow_storage()
        assert len(meta.transitions) == 1


class TestLifecycleSync:
    def test_fresh_artifact_no_transition(self):
        sync = LifecycleSync(cold_after_days=30, archive_after_days=90)
        meta = ArtifactMetadata(artifact_id="a1", name="fresh")
        result = sync.evaluate(meta)
        assert result is None

    def test_old_artifact_transitions_to_coldline(self):
        sync = LifecycleSync(cold_after_days=0, archive_after_days=90)
        meta = ArtifactMetadata(artifact_id="a1", name="old")
        meta.updated_at = time.time() - 86400  # 1 day ago
        result = sync.evaluate(meta)
        assert result == StorageClass.COLDLINE

    def test_very_old_artifact_transitions_to_archive(self):
        sync = LifecycleSync(cold_after_days=0, archive_after_days=0)
        meta = ArtifactMetadata(artifact_id="a1", name="very-old")
        meta.updated_at = time.time() - 86400 * 100
        result = sync.evaluate(meta)
        assert result == StorageClass.ARCHIVE

    def test_sync_on_list(self):
        sync = LifecycleSync(cold_after_days=1, archive_after_days=90)
        fresh = ArtifactMetadata(artifact_id="fresh", name="fresh")
        old = ArtifactMetadata(artifact_id="old", name="old")
        old.updated_at = time.time() - 86400 * 2  # 2 days old

        transitions = sync.run_sync([fresh, old])
        assert len(transitions) == 1
        assert transitions[0][0].artifact_id == "old"
        assert old.current_class == StorageClass.COLDLINE


class TestArtifactStorage:
    def test_register_artifact(self):
        store = ArtifactStorage()
        meta = store.register("a1", "test-artifact")
        assert meta.artifact_id == "a1"
        assert meta.current_class == StorageClass.STANDARD

    def test_get_returns_metadata(self):
        store = ArtifactStorage()
        meta = store.register("a1", "test")
        assert store.get("a1") is meta

    def test_get_nonexistent(self):
        store = ArtifactStorage()
        assert store.get("nonexistent") is None

    def test_get_slow_storage_warning(self, caplog):
        """Retrieval of slow-storage artifact should emit a warning."""
        import logging
        caplog.set_level(logging.WARNING)

        store = ArtifactStorage()
        meta = store.register("a1", "test")
        meta.record_transition(StorageClass.COLDLINE)

        caplog.clear()
        result = store.get("a1")
        assert result is not None
        assert "coldline storage" in caplog.text.lower()

    def test_record_explicit_transition(self):
        store = ArtifactStorage()
        store.register("a1", "test")
        assert store.record_transition("a1", StorageClass.ARCHIVE)
        meta = store.get("a1")
        assert meta.current_class == StorageClass.ARCHIVE
        assert meta.transitions[0]["reason"] == "explicit"

    def test_record_transition_nonexistent(self):
        store = ArtifactStorage()
        assert not store.record_transition("nonexistent", StorageClass.ARCHIVE)

    def test_report(self):
        store = ArtifactStorage()
        store.register("a1", "artifact-1")
        store.register("a2", "artifact-2")

        meta2 = store.get("a2")
        meta2.record_transition(StorageClass.COLDLINE)

        report = store.report()
        assert len(report) == 2

        # Find the slow artifact
        slow = [r for r in report if r["is_slow_storage"]]
        assert len(slow) == 1
        assert "warning" in slow[0]

    def test_lifecycle_sync_on_storage(self):
        store = ArtifactStorage()
        store.register("fresh", "fresh")
        store.register("old", "old")
        old_meta = store.get("old")
        old_meta.updated_at = time.time() - 86400 * 60  # 60 days

        transitions = store.run_lifecycle_sync()
        assert len(transitions) >= 1
        assert old_meta.current_class != StorageClass.STANDARD

    def test_list_slow_artifacts(self):
        store = ArtifactStorage()
        store.register("fast", "fast-one")
        slow = store.register("slow", "slow-one")
        slow.record_transition(StorageClass.COLDLINE)

        slow_list = store.list_slow_artifacts()
        assert len(slow_list) == 1
        assert slow_list[0].artifact_id == "slow"
