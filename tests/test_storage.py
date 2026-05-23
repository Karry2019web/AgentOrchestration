"""Tests for artifact download cache with checksum validation."""

import os
import tempfile

import pytest

from src.common.storage import DownloadCache


class TestDownloadCache:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = DownloadCache(cache_dir=os.path.join(self.tmpdir, "cache"))

    def teardown_method(self):
        self.cache.clear()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # put / get
    # ------------------------------------------------------------------

    def test_put_and_get(self):
        digest = self.cache.put("artifact-a", b"hello world")
        assert isinstance(digest, str) and len(digest) == 64

        retrieved = self.cache.get("artifact-a")
        assert retrieved == b"hello world"

    def test_get_missing_key(self):
        assert self.cache.get("nonexistent") is None

    def test_put_replaces_existing(self):
        self.cache.put("key1", b"first")
        self.cache.put("key1", b"second")
        assert self.cache.get("key1") == b"second"

    # ------------------------------------------------------------------
    # contains
    # ------------------------------------------------------------------

    def test_contains_returns_true_for_valid_entry(self):
        self.cache.put("x", b"data")
        assert self.cache.contains("x") is True

    def test_contains_returns_false_for_missing(self):
        assert self.cache.contains("missing") is False

    # ------------------------------------------------------------------
    # digest validation — corrupt file detection
    # ------------------------------------------------------------------

    def test_corrupt_file_is_evicted(self):
        self.cache.put("corruptible", b"original")
        entry = self.cache._load_meta("corruptible")
        with open(entry.path, "wb") as f:
            f.write(b"tampered")
        assert self.cache.get("corruptible") is None
        assert self.cache._load_meta("corruptible") is None

    def test_corrupt_file_triggers_re_download(self):
        self.cache.put("reliable", b"original data")
        entry = self.cache._load_meta("reliable")
        with open(entry.path, "wb") as f:
            f.write(b"corrupted payload")
        assert self.cache.get("reliable") is None
        self.cache.put("reliable", b"original data")
        assert self.cache.get("reliable") == b"original data"

    # ------------------------------------------------------------------
    # partial files
    # ------------------------------------------------------------------

    def test_partial_file_is_evicted(self):
        self.cache.put("partial", b"full content")
        entry = self.cache._load_meta("partial")
        with open(entry.path, "wb") as f:
            f.write(b"partial")
        assert self.cache.get("partial") is None

    # ------------------------------------------------------------------
    # evict
    # ------------------------------------------------------------------

    def test_evict_removes_entry(self):
        self.cache.put("evict-me", b"bye")
        assert self.cache.contains("evict-me") is True
        assert self.cache.evict("evict-me") is True
        assert self.cache.contains("evict-me") is False
        assert self.cache.get("evict-me") is None

    def test_evict_nonexistent_returns_false(self):
        assert self.cache.evict("nothing-here") is False

    # ------------------------------------------------------------------
    # clear
    # ------------------------------------------------------------------

    def test_clear_removes_all(self):
        self.cache.put("a", b"1")
        self.cache.put("b", b"2")
        self.cache.clear()
        assert self.cache.contains("a") is False
        assert self.cache.contains("b") is False

    # ------------------------------------------------------------------
    # list_keys
    # ------------------------------------------------------------------

    def test_list_keys(self):
        self.cache.put("k1", b"v1")
        self.cache.put("k2", b"v2")
        keys = self.cache.list_keys()
        assert "k1" in keys
        assert "k2" in keys

    def test_list_keys_after_eviction(self):
        self.cache.put("k1", b"v1")
        self.cache.put("k2", b"v2")
        self.cache.evict("k1")
        keys = self.cache.list_keys()
        assert "k1" not in keys
        assert "k2" in keys

    # ------------------------------------------------------------------
    # edge cases
    # ------------------------------------------------------------------

    def test_empty_content(self):
        digest = self.cache.put("empty", b"")
        assert isinstance(digest, str) and len(digest) == 64
        assert self.cache.get("empty") == b""

    def test_binary_content(self):
        binary = bytes(range(256))
        self.cache.put("binary", binary)
        assert self.cache.get("binary") == binary

    def test_special_characters_in_key(self):
        key = "https://example.com/artifact?v=1.0&fmt=tar.gz"
        self.cache.put(key, b"special")
        assert self.cache.get(key) == b"special"

    def test_deleted_data_file_reports_missing(self):
        self.cache.put("disappear", b"gone")
        entry = self.cache._load_meta("disappear")
        os.remove(entry.path)
        assert self.cache.get("disappear") is None
        assert self.cache.contains("disappear") is False
