"""Tests for download cache with digest verification."""

import hashlib
import os
import tempfile

import pytest

from src.common.download_cache import DownloadCache, CacheEntry, CorruptCacheError


@pytest.fixture
def cache():
    tmpdir = tempfile.mkdtemp()
    dc = DownloadCache(cache_dir=tmpdir)
    yield dc
    dc.clear()


@pytest.fixture
def sample_data():
    return b"Hello, Agent Orchestrator!"


class TestCacheEntry:
    def test_to_dict_roundtrip(self):
        e = CacheEntry("k", "/p", "abc", 42, 1000.0, 3)
        d = e.to_dict()
        r = CacheEntry.from_dict(d)
        assert r.key == "k" and r.size == 42 and r.hit_count == 3


class TestPutAndGet:
    def test_put_and_get(self, cache, sample_data):
        cache.put("a:v1", sample_data)
        data, entry = cache.get("a:v1")
        assert data == sample_data
        assert entry.key == "a:v1"

    def test_put_with_explicit_digest(self, cache, sample_data):
        d = hashlib.sha256(sample_data).hexdigest()
        cache.put("a:v2", sample_data, expected_digest=d)
        data, entry = cache.get("a:v2")
        assert data == sample_data
        assert entry.expected_digest == d

    def test_wrong_digest_raises(self, cache, sample_data):
        cache.put("a:v3", sample_data, expected_digest="0" * 64)
        with pytest.raises(CorruptCacheError):
            cache.get("a:v3")
        assert cache.peek("a:v3") is None

    def test_missing_key(self, cache):
        with pytest.raises(KeyError):
            cache.get("nonexistent")

    def test_peek(self, cache, sample_data):
        cache.put("a:v4", sample_data)
        e = cache.peek("a:v4")
        assert e is not None and e.key == "a:v4"

    def test_peek_none(self, cache):
        assert cache.peek("ghost") is None

    def test_hit_count(self, cache, sample_data):
        cache.put("a:hit", sample_data)
        _, e1 = cache.get("a:hit")
        _, e2 = cache.get("a:hit")
        assert e2.hit_count == 2


class TestCorruptDetection:
    def test_missing_file(self, cache, sample_data):
        cache.put("a:miss", sample_data)
        os.unlink(cache.peek("a:miss").file_path)
        with pytest.raises(CorruptCacheError, match="missing"):
            cache.get("a:miss")
        assert cache.peek("a:miss") is None

    def test_truncated_file(self, cache, sample_data):
        cache.put("a:trunc", sample_data)
        with open(cache.peek("a:trunc").file_path, "wb") as f:
            f.write(sample_data[:4])
        with pytest.raises(CorruptCacheError, match="size|wrong size"):
            cache.get("a:trunc")
        assert cache.peek("a:trunc") is None

    def test_modified_file(self, cache, sample_data):
        cache.put("a:mod", sample_data)
        with open(cache.peek("a:mod").file_path, "wb") as f:
            f.write(b"TAMPERED")
        with pytest.raises(CorruptCacheError, match="digest mismatch"):
            cache.get("a:mod")
        assert cache.peek("a:mod") is None


class TestEviction:
    def test_manual_evict(self, cache, sample_data):
        cache.put("a:ev", sample_data)
        assert cache.size == 1
        assert cache.evict("a:ev")
        assert cache.size == 0

    def test_evict_nonexistent(self, cache):
        assert not cache.evict("nope")

    def test_clear(self, cache, sample_data):
        cache.put("x", sample_data)
        cache.put("y", sample_data)
        assert cache.clear() == 2
        assert cache.size == 0

    def test_evict_over_limit(self, cache, sample_data):
        limited = DownloadCache(cache_dir=cache._cache_dir, max_size_mb=0)
        limited.put("first", sample_data)
        limited.put("second", sample_data)
        assert limited.peek("first") is None
        assert limited.peek("second") is not None


class TestPersistence:
    def test_metadata_survives_reload(self, cache, sample_data):
        cache.put("p:1", sample_data)
        cache.put("p:2", b"other")
        assert cache._metadata_path().exists()
        c2 = DownloadCache(cache_dir=cache._cache_dir)
        assert c2.size == 2
        data, _ = c2.get("p:1")
        assert data == sample_data

    def test_bad_metadata(self, cache):
        cache._metadata_path().write_text("{bad")
        c2 = DownloadCache(cache_dir=cache._cache_dir)
        assert c2.size == 0
