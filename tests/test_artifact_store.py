"""Tests for ArtifactStore — content digest-based deduplication."""
import pytest
from src.storage.artifact_store import ArtifactStore


class TestArtifactStore:
    def setup_method(self):
        self.store = ArtifactStore()

    def teardown_method(self):
        self.store.clear()

    def test_store_and_retrieve(self):
        data = b"hello world"
        ref = self.store.store("test.txt", data)
        assert ref.digest is not None
        assert ref.size == len(data)
        retrieved = self.store.retrieve("test.txt")
        assert retrieved == data

    def test_dedup_same_content(self):
        data = b"duplicate content"
        ref1 = self.store.store("name_a.txt", data)
        ref2 = self.store.store("name_b.txt", data)
        assert ref1.digest == ref2.digest
        assert self.store.count_blobs() == 1

    def test_same_name_different_content(self):
        ref1 = self.store.store("conflict.txt", b"version one")
        ref2 = self.store.store("conflict.txt", b"version two")
        assert ref1.digest != ref2.digest
        assert self.store.count_blobs() == 2
        assert self.store.retrieve("conflict.txt") == b"version two"

    def test_digest_mismatch_on_verify(self):
        self.store.store("tracked.bin", b"original data")
        ref = self.store.lookup("tracked.bin")
        assert ref is not None
        blob_path = self.store._blob_path(ref.digest)
        blob_path.write_text("tampered data")
        assert not self.store.verify("tracked.bin")

    def test_lookup_metadata(self):
        data = b"metadata test"
        ref = self.store.store("meta.txt", data)
        looked_up = self.store.lookup("meta.txt")
        assert looked_up is not None
        assert looked_up.digest == ref.digest
        assert looked_up.size == len(data)

    def test_has_content(self):
        data = b"unique content 42"
        assert not self.store.has_content(data)
        self.store.store("new.txt", data)
        assert self.store.has_content(data)

    def test_missing_name_returns_none(self):
        assert self.store.retrieve("nonexistent") is None
        assert self.store.lookup("nonexistent") is None

    def test_verify_ok(self):
        self.store.store("ok.bin", b"good data")
        assert self.store.verify("ok.bin")

    def test_verify_missing(self):
        assert not self.store.verify("missing.bin")

    def test_list_names(self):
        self.store.store("a.txt", b"aaa")
        self.store.store("b.txt", b"bbb")
        self.store.store("c.txt", b"ccc")
        names = self.store.list_names()
        assert sorted(names) == ["a.txt", "b.txt", "c.txt"]

    def test_blob_immutability(self):
        data = b"immutable"
        ref1 = self.store.store("first.txt", data)
        ref2 = self.store.store("second.txt", data)
        assert ref1.digest == ref2.digest
        blob_path = self.store._blob_path(ref1.digest)
        assert blob_path.exists()
        assert blob_path.read_bytes() == data
