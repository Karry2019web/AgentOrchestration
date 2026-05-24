"""Tests for the content-digest blob store."""

import pytest
from src.orchestrator.storage import (
    BlobStore,
    BlobMetadata,
    ContentDigest,
    DigestAlgorithm,
)


class TestContentDigest:
    def test_compute_sha256(self):
        digest = ContentDigest.compute(b"hello world")
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert digest == expected

    def test_compute_blake2b(self):
        digest = ContentDigest.compute(b"hello world", DigestAlgorithm.BLAKE2B)
        assert len(digest) == 128

    def test_verify_correct(self):
        data = b"test data"
        digest = ContentDigest.compute(data)
        assert ContentDigest.verify(data, digest) is True

    def test_verify_incorrect(self):
        data = b"test data"
        wrong = "0000000000000000000000000000000000000000000000000000000000000000"
        assert ContentDigest.verify(data, wrong) is False

    def test_different_content_different_digest(self):
        assert ContentDigest.compute(b"alpha") != ContentDigest.compute(b"beta")

    def test_same_content_same_digest(self):
        assert ContentDigest.compute(b"same") == ContentDigest.compute(b"same")


class TestBlobMetadata:
    def test_create_metadata(self):
        meta = BlobMetadata(digest="abc123", logical_name="report.pdf",
                            size_bytes=1024, content_type="application/pdf")
        assert meta.digest == "abc123"
        assert meta.logical_name == "report.pdf"
        assert meta.size_bytes == 1024

    def test_metadata_roundtrip(self):
        meta = BlobMetadata(digest="abc123", algorithm=DigestAlgorithm.BLAKE2B,
                            logical_name="data.bin", size_bytes=2048)
        restored = BlobMetadata.from_dict(meta.to_dict())
        assert restored.digest == meta.digest
        assert restored.algorithm == meta.algorithm


class TestBlobStore:
    def setup_method(self):
        self.store = BlobStore()

    def test_store_and_retrieve(self):
        data = b"hello, blob store"
        meta = self.store.store(data, "greeting.txt")
        assert self.store.get(meta.digest) == data

    def test_dedup_by_content_digest(self):
        data = b"duplicate content"
        m1 = self.store.store(data, "file_a.txt")
        m2 = self.store.store(data, "file_b.txt")
        assert m1.digest == m2.digest
        assert self.store.count() == 1

    def test_different_content_different_blob(self):
        self.store.store(b"content a", "file_a.txt")
        self.store.store(b"content b", "file_b.txt")
        assert self.store.count() == 2

    def test_retrieve_by_logical_name(self):
        self.store.store(b"my data", "my_file.txt")
        assert self.store.get_by_name("my_file.txt") == b"my data"

    def test_suspicious_metadata_reuse_raises(self):
        self.store.store(b"original content", "shared_name.txt")
        with pytest.raises(ValueError, match="Suspicious metadata reuse"):
            self.store.store(b"different content", "shared_name.txt")

    def test_same_logical_name_same_content_no_error(self):
        self.store.store(b"same content", "stable.txt")
        meta = self.store.store(b"same content", "stable.txt")
        assert self.store.count() == 1

    def test_has_digest(self):
        meta = self.store.store(b"test data")
        assert self.store.has(meta.digest) is True
        assert self.store.has("nonexistent") is False

    def test_get_metadata(self):
        meta = self.store.store(b"test", "test.txt", "text/plain")
        retrieved = self.store.get_metadata(meta.digest)
        assert retrieved.digest == meta.digest
        assert retrieved.logical_name == "test.txt"

    def test_get_metadata_by_name(self):
        self.store.store(b"some data", "named.txt")
        meta = self.store.get_metadata_by_name("named.txt")
        assert meta.logical_name == "named.txt"

    def test_verify_blob_valid(self):
        meta = self.store.store(b"verifiable data")
        assert self.store.verify_blob(meta.digest) is True

    def test_verify_blob_corrupted(self):
        digest = ContentDigest.compute(b"original data")
        self.store._blobs[digest] = b"tampered data"
        self.store._metadata[digest] = BlobMetadata(digest=digest)
        assert self.store.verify_blob(digest) is False

    def test_store_without_logical_name(self):
        m1 = self.store.store(b"unnamed data")
        m2 = self.store.store(b"unnamed data")
        assert m1.digest == m2.digest
        assert self.store.count() == 1

    def test_list_digests(self):
        self.store.store(b"blob a")
        self.store.store(b"blob b")
        self.store.store(b"blob c")
        assert len(self.store.list_digests()) == 3

    def test_empty_store_count(self):
        assert self.store.count() == 0
