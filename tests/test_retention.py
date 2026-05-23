"""Tests for DataRetentionManager — cascade deletion to derived embeddings."""

import pytest
from src.common.retention import (
    CASCADE_MAP,
    DataClass,
    DataRetentionManager,
    DataStore,
    DeletionEntry,
    DeletionManifest,
    StoreRegistry,
)


class TestDataClass:
    def test_cascade_map_is_complete(self):
        """Every DataClass appears in CASCADE_MAP exactly once."""
        for dc in DataClass:
            assert dc in CASCADE_MAP, f"{dc} missing from CASCADE_MAP"
        assert len(CASCADE_MAP) == len(list(DataClass))

    def test_task_artifact_cascades_to_embeddings_and_indexes(self):
        assert CASCADE_MAP[DataClass.TASK_ARTIFACT] == {
            DataClass.DERIVED_EMBEDDING,
            DataClass.DERIVED_INDEX,
        }


class TestDeletionManifest:
    def test_empty_manifest_is_successful(self):
        m = DeletionManifest()
        assert m.all_successful
        assert m.total_removed == 0

    def test_manifest_reports_failures(self):
        m = DeletionManifest()
        m.add_entry(DeletionEntry(store=DataClass.TASK_ARTIFACT, removed_count=3))
        m.add_entry(DeletionEntry(store=DataClass.DERIVED_EMBEDDING, errors=["timeout"]))
        assert not m.all_successful
        assert m.total_removed == 3

    def test_summary_includes_all_stores(self):
        m = DeletionManifest()
        m.add_entry(DeletionEntry(store=DataClass.TASK_ARTIFACT, removed_count=2))
        summary = m.summary()
        assert "task_artifact" in summary
        assert DataClass.TASK_ARTIFACT.value in summary


class TestDataStore:
    def test_delete_by_owner_removes_matching_records(self):
        store = DataStore(DataClass.TASK_ARTIFACT)
        store.load({"owner-a:k1": 1, "owner-a:k2": 2, "owner-b:k3": 3})
        assert store.delete_by_owner("owner-a") == 2
        assert store.size() == 1
        assert "owner-b:k3" in store.keys()

    def test_delete_by_owner_no_match(self):
        store = DataStore(DataClass.EXECUTION_LOG)
        store.load({"owner-a:k1": 1})
        assert store.delete_by_owner("nonexistent") == 0
        assert store.size() == 1


class TestDataRetentionManager:
    def test_delete_owner_data_removes_primary_only(self):
        mgr = DataRetentionManager()

        # Seed some data
        mgr.registry.get(DataClass.TASK_ARTIFACT).load({"owner-1:k1": "a", "owner-2:k2": "b"})
        mgr.registry.get(DataClass.DERIVED_EMBEDDING).load({"owner-1:e1": [0.1]})

        manifest = mgr.delete_owner_data("owner-1", primary_classes=[DataClass.TASK_ARTIFACT])

        assert DataClass.TASK_ARTIFACT in manifest.entries
        # Derived embedding should also be affected via cascade
        assert DataClass.DERIVED_EMBEDDING in manifest.entries
        assert manifest.entries[DataClass.TASK_ARTIFACT].removed_count == 1
        assert mgr.registry.get(DataClass.TASK_ARTIFACT).size() == 1  # owner-2 remains

    def test_delete_from_all_stores_when_primary_is_none(self):
        mgr = DataRetentionManager()
        mgr.registry.get(DataClass.WORKFLOW_STATE).load({"task-1:state": {}})
        mgr.registry.get(DataClass.DERIVED_INDEX).load({"task-1:idx": "abc"})

        manifest = mgr.delete_owner_data("task-1")

        assert manifest.all_successful
        assert manifest.total_removed == 2

    def test_reconcile_detects_stale_embeddings(self):
        mgr = DataRetentionManager()
        # Embedding exists but the primary owner store is empty
        mgr.registry.get(DataClass.DERIVED_EMBEDDING).load({"orphan:e1": [0.5]})
        mgr.registry.get(DataClass.DERIVED_INDEX).load({"orphan:ix1": "data"})

        stale = mgr.reconcile_all()
        assert "derived_embedding" in stale
        assert stale["derived_embedding"] >= 1

    def test_error_in_one_store_does_not_block_others(self):
        mgr = DataRetentionManager()
        mgr.registry.get(DataClass.TASK_ARTIFACT).load({"o1:k1": 1})
        mgr.registry.get(DataClass.DERIVED_EMBEDDING).load({"o1:e1": [0.1]})

        manifest = mgr.delete_owner_data("o1")

        # Both should have entries even if one had an error
        assert DataClass.TASK_ARTIFACT in manifest.entries
        assert DataClass.DERIVED_EMBEDDING in manifest.entries
        # All should be successful here
        assert manifest.all_successful
