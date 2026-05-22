"""Artifact download cache with checksum validation.

Stores expected content digests alongside cached artifacts and verifies
them before returning cache hits. Corrupt entries are automatically
evicted and re-downloaded.
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple


class DownloadCache:
    """A disk-backed cache for downloaded artifacts with integrity verification.

    Each cached artifact stores:
    - The raw file content at ``cache_path / <key> / artifact``
    - Metadata (including the expected SHA-256 digest) at ``cache_path / <key> / meta.json``

    On cache hit the stored content is re-hashed and compared against the
    expected digest before the caller gets a hit.  If the hash does not
    match the entry is evicted and ``None`` is returned so the caller
    re-downloads.
    """

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        self._cache_dir = Path(cache_dir or tempfile.mkdtemp(prefix="ao_cache_"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def cache_dir(self) -> Path:
        """The root directory holding all cache entries."""
        return self._cache_dir

    def get(self, key: str, expected_digest: str, algorithm: str = "sha256") -> Optional[bytes]:
        """Return cached content for *key* if it passes integrity check.

        Parameters
        ----------
        key:
            Unique cache key (e.g. an artifact download URL or content
            address).
        expected_digest:
            The hex-encoded digest the content is expected to have.
        algorithm:
            Hash algorithm name (default ``"sha256"``).  Must be
            available via ``hashlib.new()``.

        Returns
        -------
        The cached bytes if the entry exists and the content digest
        matches **expected_digest**; ``None`` if there is a cache miss
        or the content is corrupt (in which case the entry is evicted).
        """
        entry = self._locate(key)
        if entry is None:
            return None

        content_path, meta_path = entry

        # ---- 1. Load metadata ----
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._evict(key)
            return None

        stored_digest = meta.get("digest")
        stored_algo = meta.get("algorithm", "sha256")
        if stored_digest is None:
            self._evict(key)
            return None

        # ---- 2. Verify content integrity ----
        try:
            raw = content_path.read_bytes()
        except OSError:
            self._evict(key)
            return None

        actual_digest = _digest(raw, stored_algo)
        if actual_digest != stored_digest:
            self._evict(key)
            return None

        return raw

    def put(self, key: str, content: bytes,
            expected_digest: Optional[str] = None,
            algorithm: str = "sha256") -> str:
        """Store *content* in the cache under *key*.

        Parameters
        ----------
        key:
            Unique cache key.
        content:
            Raw bytes to cache.
        expected_digest:
            Optional caller-provided digest.  If ``None`` the digest is
            computed from *content* at this call.
        algorithm:
            Hash algorithm name.

        Returns
        -------
        The hex digest that was stored.
        """
        entry_dir = self._cache_dir / _sanitise_key(key)
        entry_dir.mkdir(parents=True, exist_ok=True)

        content_path = entry_dir / "artifact"
        meta_path = entry_dir / "meta.json"

        if expected_digest is not None:
            stored_digest = expected_digest
        else:
            stored_digest = _digest(content, algorithm)

        content_path.write_bytes(content)
        meta_path.write_text(
            json.dumps({
                "digest": stored_digest,
                "algorithm": algorithm,
                "size": len(content),
            }),
            encoding="utf-8",
        )
        return stored_digest

    def invalidate(self, key: str) -> bool:
        """Remove a single cache entry."""
        return self._evict(key)

    def clear(self) -> int:
        """Remove all cache entries."""
        count = 0
        for entry in self._cache_dir.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
                count += 1
        return count

    def has(self, key: str) -> bool:
        """Check whether *key* has a cached entry (without verifying integrity)."""
        entry_dir = self._cache_dir / _sanitise_key(key)
        return entry_dir.is_dir() and (entry_dir / "artifact").is_file()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _locate(self, key: str) -> Optional[Tuple[Path, Path]]:
        entry_dir = self._cache_dir / _sanitise_key(key)
        content_path = entry_dir / "artifact"
        meta_path = entry_dir / "meta.json"
        if content_path.is_file() and meta_path.is_file():
            return content_path, meta_path
        return None

    def _evict(self, key: str) -> bool:
        entry_dir = self._cache_dir / _sanitise_key(key)
        if entry_dir.is_dir():
            shutil.rmtree(entry_dir, ignore_errors=True)
            return True
        return False


def _sanitise_key(key: str) -> str:
    """Make a cache-key string safe for use as a directory name."""
    safe = ""
    for ch in key:
        if ch.isalnum() or ch in "._-":
            safe += ch
        else:
            safe += f"_{ord(ch):02x}"
    if len(safe) > 120:
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        safe = safe[:100] + "_" + h
    return safe


def _digest(data: bytes, algorithm: str = "sha256") -> str:
    return hashlib.new(algorithm, data).hexdigest()
