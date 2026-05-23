"""Storage — Artifact download cache with checksum validation."""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Optional


class CacheEntry:
    """Metadata for a cached artifact."""

    def __init__(self, key: str, expected_digest: str, path: str):
        self.key = key
        self.expected_digest = expected_digest
        self.path = path

    def to_dict(self) -> dict:
        return {"key": self.key, "expected_digest": self.expected_digest, "path": self.path}

    @classmethod
    def from_dict(cls, data: dict) -> "CacheEntry":
        return cls(data["key"], data["expected_digest"], data["path"])


class _DigestMismatchError(Exception):
    """Raised when cached content does not match its expected digest."""
    pass


class DownloadCache:
    """Local artifact download cache with content digest validation.

    Stores downloaded artifacts keyed by an identifier (e.g. URL or artifact
    name). Each entry is paired with a SHA-256 digest computed from the
    original download. Before returning a cache hit, the stored content is
    rehashed and compared against the recorded digest.  Corrupt entries are
    evicted automatically so the next access triggers a fresh download.
    """

    def __init__(self, cache_dir: str = ".cache/artifacts"):
        self._cache_dir = Path(cache_dir)
        self._meta_dir = self._cache_dir / ".meta"
        self._meta_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[bytes]:
        """Return cached bytes for *key* if the content is valid.

        Returns ``None`` when:
        * the key does not exist in the cache, or
        * the stored content digest does not match (entry is evicted).
        """
        entry = self._load_meta(key)
        if entry is None:
            return None

        file_path = Path(entry.path)
        if not file_path.exists():
            self._evict(key)
            return None

        actual_digest = self._hash_file(file_path)
        if actual_digest != entry.expected_digest:
            self._evict(key)
            return None

        return file_path.read_bytes()

    def put(self, key: str, content: bytes) -> str:
        """Store *content* under *key* and return its SHA-256 digest.

        If the key already exists the previous entry is replaced.
        """
        digest = hashlib.sha256(content).hexdigest()
        file_path = self._cache_dir / _safe_filename(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

        entry = CacheEntry(key=key, expected_digest=digest, path=str(file_path))
        self._save_meta(key, entry)
        return digest

    def contains(self, key: str) -> bool:
        """Check whether *key* exists in cache *and* passes digest validation."""
        entry = self._load_meta(key)
        if entry is None:
            return False
        file_path = Path(entry.path)
        if not file_path.exists():
            self._evict(key)
            return False
        actual_digest = self._hash_file(file_path)
        if actual_digest != entry.expected_digest:
            self._evict(key)
            return False
        return True

    def evict(self, key: str) -> bool:
        """Remove *key* from the cache.  Returns ``True`` if it existed."""
        return self._evict(key)

    def clear(self) -> None:
        """Remove all cached artifacts and metadata."""
        shutil.rmtree(self._cache_dir, ignore_errors=True)

    def list_keys(self) -> list:
        """Return all cached keys."""
        keys = []
        for fname in os.listdir(self._meta_dir):
            if fname.endswith(".json"):
                keys.append(fname[:-5])
        return keys

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _meta_path(self, key: str) -> Path:
        safe = _safe_filename(key)
        return self._meta_dir / f"{safe}.json"

    def _load_meta(self, key: str) -> Optional[CacheEntry]:
        meta_path = self._meta_path(key)
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text())
            return CacheEntry.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            self._evict(key)
            return None

    def _save_meta(self, key: str, entry: CacheEntry) -> None:
        meta_path = self._meta_path(key)
        meta_path.write_text(json.dumps(entry.to_dict()))

    def _evict(self, key: str) -> bool:
        entry = self._load_meta(key)
        file_path = Path(entry.path) if entry else self._cache_dir / _safe_filename(key)
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        meta_path = self._meta_path(key)
        if meta_path.exists():
            meta_path.unlink(missing_ok=True)
        return entry is not None

    @staticmethod
    def _hash_file(path: Path) -> str:
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()


def _safe_filename(key: str) -> str:
    """Produce a filesystem-safe name from an arbitrary key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
