"""Download Cache — Content-addressed local cache with digest verification."""

import hashlib
import json
import logging
import time
from pathlib import Path
from threading import Lock
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CacheEntry:
    """Metadata for a single cached download."""

    def __init__(self, key: str, file_path: str, expected_digest: str,
                 size: int = 0, created_at: Optional[float] = None, hit_count: int = 0):
        self.key = key
        self.file_path = file_path
        self.expected_digest = expected_digest
        self.size = size
        self.created_at = created_at or time.time()
        self.hit_count = hit_count

    def to_dict(self) -> dict:
        return {"key": self.key, "file_path": self.file_path,
                "expected_digest": self.expected_digest, "size": self.size,
                "created_at": self.created_at, "hit_count": self.hit_count}

    @classmethod
    def from_dict(cls, data: dict) -> "CacheEntry":
        return cls(data["key"], data["file_path"], data["expected_digest"],
                   data.get("size", 0), data.get("created_at"), data.get("hit_count", 0))


class CorruptCacheError(Exception):
    """Raised when a cache entry fails digest verification."""
    pass


class DownloadCache:
    """Content-addressable download cache with digest verification."""

    def __init__(self, cache_dir: str, max_size_mb: int = 1024):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._lock = Lock()
        self._entries: Dict[str, CacheEntry] = {}
        self._load_metadata()

    def put(self, key: str, data: bytes, expected_digest: Optional[str] = None) -> CacheEntry:
        digest = expected_digest or self._compute_digest(data)
        file_path = self._file_path_for(key)
        with open(file_path, "wb") as f:
            f.write(data)
        entry = CacheEntry(key, str(file_path), digest, len(data))
        with self._lock:
            self._entries[key] = entry
            self._evict_if_over_limit()
            self._save_metadata()
        return entry

    def get(self, key: str) -> Tuple[bytes, CacheEntry]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise KeyError(f"Cache miss: {key}")
        file_path = Path(entry.file_path)
        if not file_path.exists():
            self._evict(key, "file missing")
            raise CorruptCacheError(f"Cached file for {key} is missing")
        actual_size = file_path.stat().st_size
        if actual_size != entry.size:
            self._evict(key, "size mismatch")
            raise CorruptCacheError(f"Cached file for {key} wrong size")
        actual_digest = self._digest_of_file(file_path)
        if actual_digest != entry.expected_digest:
            self._evict(key, "digest mismatch")
            raise CorruptCacheError(f"Cached file for {key} digest mismatch")
        with open(file_path, "rb") as f:
            data = f.read()
        with self._lock:
            entry.hit_count += 1
            self._save_metadata()
        return data, entry

    def peek(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            e = self._entries.get(key)
            return CacheEntry.from_dict(e.to_dict()) if e else None

    def evict(self, key: str) -> bool:
        with self._lock:
            return self._evict(key, "manual eviction")

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            for entry in self._entries.values():
                try:
                    Path(entry.file_path).unlink(missing_ok=True)
                except OSError:
                    pass
            self._entries.clear()
            self._save_metadata()
            return count

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return sum(e.size for e in self._entries.values())

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._entries), "total_bytes": self.total_bytes,
                    "max_bytes": self._max_size_bytes, "cache_dir": str(self._cache_dir)}

    def _file_path_for(self, key: str) -> Path:
        return self._cache_dir / hashlib.md5(key.encode()).hexdigest()

    def _compute_digest(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _digest_of_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _evict(self, key: str, reason: str) -> bool:
        entry = self._entries.pop(key, None)
        if entry is None:
            return False
        try:
            Path(entry.file_path).unlink(missing_ok=True)
        except OSError:
            pass
        self._save_metadata()
        logger.warning("Evicted %s from cache (%s)", key, reason)
        return True

    def _evict_if_over_limit(self) -> None:
        while self.total_bytes > self._max_size_bytes and self._entries:
            oldest = min(self._entries, key=lambda k: self._entries[k].created_at)
            self._evict(oldest, "cache size limit")

    def _metadata_path(self) -> Path:
        return self._cache_dir / "cache_metadata.json"

    def _save_metadata(self) -> None:
        try:
            tmp = self._metadata_path().with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._entries.items()}, f, indent=2)
            tmp.replace(self._metadata_path())
        except OSError:
            pass

    def _load_metadata(self) -> None:
        meta = self._metadata_path()
        if not meta.exists():
            return
        try:
            with open(meta) as f:
                for k, v in json.load(f).items():
                    self._entries[k] = CacheEntry.from_dict(v)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load cache metadata: %s", exc)
