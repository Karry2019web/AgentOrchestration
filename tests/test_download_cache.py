"""Tests for the artifact download cache with checksum validation."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from src.storage.cache import DownloadCache, _digest, _sanitise_key


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def cache():
    """Provide a fresh ``DownloadCache`` backed by a temporary directory."""
    tmp = tempfile.mkdtemp()
    yield DownloadCache(cache_dir=tmp)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------
# put / get  —  happy path
# ------------------------------------------------------------------

class TestPutAndGet:
    def test_put_and_get(self, cache: DownloadCache):
        data = b"hello world, this is an artifact"
        key = "artifacts/v1/task-123/output.bin"
        cache.put(key, data)
        d = _digest(data)
        assert cache.get(key, d) == data

    def test_put_with_caller_provided_digest(self, cache: DownloadCache):
        data = b"artifact data with caller digest"
        key = "task-456"
        expected = _digest(data)
        cache.put(key, data, expected_digest=expected)
        assert cache.get(key, expected) == data

    def test_multiple_keys(self, cache: DownloadCache):
        pairs = {
            "k1": b"data-one",
            "k2": b"data-two",
            "k3": b"data-three",
        }
        for key, data in pairs.items():
            cache.put(key, data)
        for key, data in pairs.items():
            d = _digest(data)
            assert cache.get(key, d) == data

    def test_get_cache_miss(self, cache: DownloadCache):
        assert cache.get("nonexistent", "abcd1234") is None

    def test_put_returns_digest(self, cache: DownloadCache):
        data = b"some content"
        returned = cache.put("k", data)
        assert returned == _digest(data)

    def test_put_with_caller_digest_returns_caller_digest(self, cache: DownloadCache):
        data = b"some content"
        caller_digest = "aa" * 16  # 256-bit fake, OK for storage
        returned = cache.put("k", data, expected_digest=caller_digest)
        assert returned == caller_digest


# ------------------------------------------------------------------
# Corrupt / tampered content  →  eviction
# ------------------------------------------------------------------

class TestCorruption:
    def test_corrupt_file_evicts(self, cache: DownloadCache):
        data = b"original artifact"
        key = "corrupt-test"
        d = _digest(data)
        cache.put(key, data)

        # Tamper with the artifact file on disk
        entry_dir = cache.cache_dir / _sanitise_key(key)
        artifact_file = entry_dir / "artifact"
        artifact_file.write_bytes(b"TAMPERED DATA")

        # get() should detect mismatch, evict, return None
        assert cache.get(key, d) is None
        assert not cache.has(key)

    def test_deleted_artifact_file_evicts(self, cache: DownloadCache):
        data = b"original"
        key = "delete-test"
        d = _digest(data)
        cache.put(key, data)

        entry_dir = cache.cache_dir / _sanitise_key(key)
        (entry_dir / "artifact").unlink()

        assert cache.get(key, d) is None

    def test_corrupt_metadata_evicts(self, cache: DownloadCache):
        data = b"original"
        key = "meta-corrupt"
        d = _digest(data)
        cache.put(key, data)

        entry_dir = cache.cache_dir / _sanitise_key(key)
        (entry_dir / "meta.json").write_text("not-json")

        assert cache.get(key, d) is None
        assert not cache.has(key)

    def test_empty_metadata_digest_evicts(self, cache: DownloadCache):
        data = b"original"
        key = "empty-digest"
        d = _digest(data)
        cache.put(key, data)

        entry_dir = cache.cache_dir / _sanitise_key(key)
        meta = json.loads((entry_dir / "meta.json").read_text())
        del meta["digest"]
        (entry_dir / "meta.json").write_text(json.dumps(meta))

        assert cache.get(key, d) is None
        assert not cache.has(key)

    def test_partial_file(self, cache: DownloadCache):
        """A truncated artifact file should be detected and evicted."""
        data = b"original artifact content that is longer"
        key = "partial-test"
        d = _digest(data)
        cache.put(key, data)

        entry_dir = cache.cache_dir / _sanitise_key(key)
        # Truncate to first 10 bytes
        artifact = entry_dir / "artifact"
        artifact.write_bytes(artifact.read_bytes()[:10])

        assert cache.get(key, d) is None
        assert not cache.has(key)


# ------------------------------------------------------------------
# invalidation
# ------------------------------------------------------------------

class TestInvalidation:
    def test_invalidate_removes_entry(self, cache: DownloadCache):
        cache.put("k", b"data")
        assert cache.has("k")
        assert cache.invalidate("k") is True
        assert not cache.has("k")

    def test_invalidate_nonexistent(self, cache: DownloadCache):
        assert cache.invalidate("nosuch") is False

    def test_clear_removes_all(self, cache: DownloadCache):
        cache.put("a", b"1")
        cache.put("b", b"2")
        cache.put("c", b"3")
        assert cache.clear() == 3
        assert not cache.has("a")


# ------------------------------------------------------------------
# has
# ------------------------------------------------------------------

class TestHas:
    def test_has_after_put(self, cache: DownloadCache):
        cache.put("k", b"data")
        assert cache.has("k")

    def test_has_miss(self, cache: DownloadCache):
        assert not cache.has("nonexistent")

    def test_has_after_eviction(self, cache: DownloadCache):
        cache.put("k", b"data")
        cache.invalidate("k")
        assert not cache.has("k")


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_content(self, cache: DownloadCache):
        data = b""
        key = "empty"
        cache.put(key, data)
        d = _digest(data)
        assert cache.get(key, d) == b""

    def test_large_content(self, cache: DownloadCache):
        data = os.urandom(1024 * 512)  # 512 KiB
        key = "large"
        d = _digest(data)
        cache.put(key, data)
        assert cache.get(key, d) == data

    def test_url_special_chars_in_key(self, cache: DownloadCache):
        key = "https://storage.example.com/artifacts/v1?project=my-app&file=output.tgz"
        data = b"url-keyed artifact"
        cache.put(key, data)
        d = _digest(data)
        assert cache.get(key, d) == data

    def test_unicode_in_key(self, cache: DownloadCache):
        key = "artífàcts/文件/data.bin"
        data = b"unicode in key"
        cache.put(key, data)
        d = _digest(data)
        assert cache.get(key, d) == data

    def test_different_algorithm(self, cache: DownloadCache):
        data = b"sha512 content"
        key = "sha512-test"
        algo = "sha512"
        d = _digest(data, algo)
        cache.put(key, data, algorithm=algo)
        assert cache.get(key, d, algorithm=algo) == data

    def test_get_after_reinit_same_dir(self):
        """Data survives across DownloadCache instances pointing to the same directory."""
        tmp = tempfile.mkdtemp()
        try:
            c1 = DownloadCache(cache_dir=tmp)
            data = b"persistent data"
            key = "persist"
            d = _digest(data)
            c1.put(key, data)

            c2 = DownloadCache(cache_dir=tmp)
            assert c2.get(key, d) == data
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------
# Helper tests
# ------------------------------------------------------------------

class TestSanitiseKey:
    def test_alphanumeric_unchanged(self):
        assert _sanitise_key("abc123.def-ghi_jkl") == "abc123.def-ghi_jkl"

    def test_special_chars_encoded(self):
        safe = _sanitise_key("a/b c")
        assert "2f" in safe  # ord("/") = 0x2F
        assert "20" in safe  # ord(" ") = 0x20

    def test_long_key_truncated(self):
        long_key = "x" * 200
        safe = _sanitise_key(long_key)
        assert len(safe) <= 120
        assert "_" in safe  # separator before hash


class TestDigest:
    def test_sha256(self):
        d = _digest(b"hello", "sha256")
        assert d == hashlib.sha256(b"hello").hexdigest()

    def test_sha512(self):
        d = _digest(b"hello", "sha512")
        assert d == hashlib.sha512(b"hello").hexdigest()

    def test_default_is_sha256(self):
        assert _digest(b"hello") == hashlib.sha256(b"hello").hexdigest()
