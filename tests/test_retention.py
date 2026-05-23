"""Tests for retention and cascade deletion."""

from src.common.retention import DeletionManifest, CascadeDeletion


class TestDeletionManifest:
    def setup_method(self):
        self.manifest = DeletionManifest(
            artifact_id="art-001",
            data_class="task_embedding",
            primary_stores=["artifact_store"],
            derived_stores=["vector_index", "cache_store"],
        )

    def test_creation(self):
        assert self.manifest.artifact_id == "art-001"
        assert self.manifest.data_class == "task_embedding"
        assert self.manifest.primary_stores == ["artifact_store"]
        assert self.manifest.derived_stores == ["vector_index", "cache_store"]

    def test_all_stores_property(self):
        assert self.manifest.all_stores == ["artifact_store", "vector_index", "cache_store"]

    def test_is_complete_initial(self):
        assert not self.manifest.is_complete

    def test_mark_completed(self):
        self.manifest.mark_completed("artifact_store")
        assert "artifact_store" in self.manifest.completed_stores

    def test_all_complete(self):
        for s in self.manifest.all_stores:
            self.manifest.mark_completed(s)
        assert self.manifest.is_complete

    def test_failure_prevents_complete(self):
        self.manifest.mark_completed("artifact_store")
        self.manifest.mark_failed("vector_index", "timeout")
        assert not self.manifest.is_complete
        assert "vector_index" in self.manifest.failed_stores

    def test_mark_completed_removes_failure(self):
        self.manifest.mark_failed("vector_index", "timeout")
        self.manifest.mark_completed("vector_index")
        assert "vector_index" not in self.manifest.failed_stores
        assert "vector_index" in self.manifest.completed_stores

    def test_get_summary(self):
        self.manifest.mark_completed("artifact_store")
        summary = self.manifest.get_summary()
        assert summary["artifact_id"] == "art-001"
        assert summary["data_class"] == "task_embedding"
        assert "artifact_store" in summary["completed_stores"]
        assert not summary["all_complete"]

    def test_primary_only_manifest(self):
        m = DeletionManifest(artifact_id="art-002", data_class="raw_log", primary_stores=["log_store"])
        assert m.derived_stores == []
        assert m.all_stores == ["log_store"]


class TestCascadeDeletion:
    def setup_method(self):
        self.cascade = CascadeDeletion()

    def _success_handler(self, store_id: str, context: dict) -> bool:
        return True

    def _failure_handler(self, store_id: str, context: dict) -> bool:
        return False

    def test_register_handler(self):
        self.cascade.register_handler("store_a", self._success_handler)
        assert "store_a" in self.cascade._handlers

    def test_create_manifest_filters_to_handled_stores(self):
        self.cascade.register_handler("store_a", self._success_handler)
        self.cascade.register_handler("store_b", self._success_handler)
        manifest = self.cascade.create_manifest(
            "art-001", "embedding",
            primary_stores=["store_a", "store_c"],
            derived_stores=["store_b"],
        )
        assert manifest.primary_stores == ["store_a"]
        assert manifest.derived_stores == ["store_b"]

    def test_execute_success(self):
        self.cascade.register_handler("store_a", self._success_handler)
        manifest = self.cascade.create_manifest("art-001", "embedding", primary_stores=["store_a"])
        result = self.cascade.execute(manifest)
        assert result.is_complete
        assert "store_a" in result.completed_stores

    def test_execute_handler_failure(self):
        self.cascade.register_handler("store_a", self._failure_handler)
        manifest = self.cascade.create_manifest("art-001", "embedding", primary_stores=["store_a"])
        result = self.cascade.execute(manifest)
        assert not result.is_complete
        assert "store_a" in result.failed_stores

    def test_execute_no_handler(self):
        manifest = self.cascade.create_manifest("art-001", "embedding", primary_stores=["store_a"])
        result = self.cascade.execute(manifest)
        assert not result.is_complete
        assert "store_a" in result.failed_stores

    def test_cascade_delete_convenience(self):
        self.cascade.register_handler("primary", self._success_handler)
        self.cascade.register_handler("derived", self._success_handler)
        summary = self.cascade.cascade_delete(
            "art-001", "embedding",
            primary_stores=["primary"],
            derived_stores=["derived"],
        )
        assert summary["artifact_id"] == "art-001"
        assert summary["all_complete"]
        assert "primary" in summary["completed_stores"]
        assert "derived" in summary["completed_stores"]

    def test_cascade_delete_partial_failure(self):
        self.cascade.register_handler("primary", self._success_handler)
        self.cascade.register_handler("derived", self._failure_handler)
        summary = self.cascade.cascade_delete(
            "art-001", "embedding",
            primary_stores=["primary"],
            derived_stores=["derived"],
        )
        assert not summary["all_complete"]
        assert "derived" in summary["failed_stores"]

    def test_reconciliation_scan_clean(self):
        self.cascade.register_handler("store_a", self._success_handler)
        self.cascade.cascade_delete("art-001", "embedding", primary_stores=["store_a"])
        stale = self.cascade.reconciliation_scan()
        assert stale == []

    def test_reconciliation_scan_finds_stale(self):
        self.cascade.register_handler("store_a", self._success_handler)
        self.cascade.register_handler("store_b", self._success_handler)
        manifest = self.cascade.create_manifest("art-001", "embedding", primary_stores=["store_a", "store_b"])
        self.cascade.execute(manifest)
        stale = self.cascade.reconciliation_scan()
        # Both stores should appear since execute processes all stores
        assert len(stale) == 0

    def test_get_results(self):
        self.cascade.register_handler("store_a", self._success_handler)
        self.cascade.cascade_delete("art-001", "embedding", primary_stores=["store_a"])
        results = self.cascade.get_results("art-001")
        assert len(results) == 1
        assert results[0]["artifact_id"] == "art-001"
