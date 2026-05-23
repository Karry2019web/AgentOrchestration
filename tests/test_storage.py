import pytest
from src.common.errors import ArtifactNotFoundError
from src.agent.storage import CrossRegionArtifactReader, DEFAULT_REPLICATION_WINDOW


class TestCrossRegionArtifactReader:
    def setup_method(self):
        self.reader = CrossRegionArtifactReader(regions=["us-east", "us-west", "eu-central"])

    def test_record_and_read_from_origin(self):
        data = b"hello world, this is a test artifact"
        self.reader.record_artifact("art-001", data, "us-east")
        result = self.reader.read_artifact("art-001", "us-east")
        assert result == data

    def test_read_with_replication_lag(self):
        data = b"cross-region artifact data"
        self.reader.record_artifact("art-002", data, "us-east")
        with pytest.raises(ArtifactNotFoundError) as exc_info:
            self.reader.read_artifact("art-002", "us-west")
        assert "retries exhausted" in str(exc_info.value)

    def test_read_after_replication_acknowledged(self):
        data = b"replicated artifact"
        self.reader.record_artifact("art-003", data, "us-east")
        self.reader.acknowledge_replication("art-003", "us-west")
        result = self.reader.read_artifact("art-003", "us-west")
        assert result == data

    def test_permanently_missing_artifact(self):
        with pytest.raises(ArtifactNotFoundError) as exc_info:
            self.reader.read_artifact("nonexistent-artifact", "us-east")
        assert "permanently_missing" in str(exc_info.value)

    def test_read_after_replication_window_expiry(self):
        data = b"expiring artifact"
        self.reader.record_artifact("art-004", data, "us-east")
        self.reader.expire_replication("art-004", "us-west")
        with pytest.raises(ArtifactNotFoundError) as exc_info:
            self.reader.read_artifact("art-004", "us-west")
        assert "expired" in str(exc_info.value)

    def test_digest_mismatch_detection(self):
        data = b"original data"
        self.reader.record_artifact("art-005", data, "us-east")
        self.reader.acknowledge_replication("art-005", "us-west")
        old = self.reader._in_memory_store.copy()
        try:
            self.reader._in_memory_store[("art-005", "us-west")] = b"corrupted data"
            with pytest.raises(ArtifactNotFoundError) as exc_info:
                self.reader.read_artifact("art-005", "us-west")
            assert "retries exhausted" in str(exc_info.value)
        finally:
            self.reader._in_memory_store = old

    def test_error_includes_metadata_state(self):
        with pytest.raises(ArtifactNotFoundError) as exc_info:
            self.reader.read_artifact("missing-art", "eu-central")
        assert exc_info.value.region == "eu-central"
        assert exc_info.value.metadata_state == "permanently_missing"
        assert exc_info.value.artifact_id == "missing-art"

    def test_replication_window_default(self):
        assert DEFAULT_REPLICATION_WINDOW == 300

    def test_verify_digest_matches(self):
        data = b"artifact content"
        self.reader.record_artifact("art-006", data, "us-east")
        digest = self.reader._digest_cache["art-006"]
        assert self.reader._verify_digest(data, digest) is True

    def test_verify_digest_mismatch(self):
        data = b"original content"
        self.reader.record_artifact("art-007", data, "us-east")
        digest = self.reader._digest_cache["art-007"]
        assert self.reader._verify_digest(b"different content", digest) is False

    def test_replication_age_tracking(self):
        data = b"tracked artifact"
        self.reader.record_artifact("art-008", data, "us-east")
        age = self.reader._get_replication_age("art-008", "us-west")
        assert age is not None and age >= 0

    def test_record_generates_digest(self):
        digest = self.reader.record_artifact("art-009", b"data", "us-east")
        assert len(digest.sha256) == 64 and digest.size == 4 and digest.region_origin == "us-east"

    def test_multiple_regions_initialization(self):
        reader = CrossRegionArtifactReader(regions=["us-east", "us-west", "eu-west", "ap-southeast"], replication_window=600, max_retries=3)
        assert len(reader.regions) == 4 and reader.replication_window == 600 and reader.max_retries == 3

    def test_get_replication_age_for_pending_artifact(self):
        assert self.reader._get_replication_age("non-existent", "us-east") is None
