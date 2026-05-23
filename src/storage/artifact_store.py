"""
Artifact Store — Content-addressed blob storage with content digest deduplication.

Computes SHA-256 digest before any dedup decision, ensuring that distinct
artifacts are never treated as duplicates or linked to the wrong blob.
All blob references are immutable — once stored, content is never overwritten.
"""

import hashlib
import os
import shutil
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class BlobRef:
    """Immutable reference to a stored blob."""
    digest: str
    size: int
    stored_at: str


class ArtifactStore:
    """Content-addressed blob store with verified digest deduplication."""

    def __init__(self, base_path="/tmp/ao_artifacts"):
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)
        self._blobs: Dict[str, BlobRef] = {}
        self._metadata: Dict[str, str] = {}

    def store(self, logical_name: str, data: bytes) -> BlobRef:
        """Store artifact data under a logical name."""
        digest = self._compute_digest(data)

        existing = self._blobs.get(digest)
        if existing is not None:
            self._metadata[logical_name] = digest
            return existing

        blob_path = self._blob_path(digest)
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(data)

        ref = BlobRef(
            digest=digest,
            size=len(data),
            stored_at=datetime.now(timezone.utc).isoformat(),
        )
        self._blobs[digest] = ref
        self._metadata[logical_name] = digest
        return ref

    def retrieve(self, logical_name: str) -> Optional[bytes]:
        """Retrieve artifact bytes by logical name."""
        digest = self._metadata.get(logical_name)
        if digest is None:
            return None
        blob_path = self._blob_path(digest)
        if not blob_path.exists():
            return None
        return blob_path.read_bytes()

    def lookup(self, logical_name: str) -> Optional[BlobRef]:
        """Get blob metadata for a logical artifact name."""
        digest = self._metadata.get(logical_name)
        if digest is None:
            return None
        return self._blobs.get(digest)

    def verify(self, logical_name: str) -> bool:
        """Verify stored content matches its registered digest."""
        blob_ref = self.lookup(logical_name)
        if blob_ref is None:
            return False
        data = self.retrieve(logical_name)
        if data is None:
            return False
        actual = self._compute_digest(data)
        return actual == blob_ref.digest

    def has_content(self, data: bytes) -> bool:
        """Check if content with this digest already exists."""
        digest = self._compute_digest(data)
        return digest in self._blobs

    def has_name(self, logical_name: str) -> bool:
        """Check if a logical name is registered."""
        return logical_name in self._metadata

    def list_names(self):
        """Return all registered logical names."""
        return list(self._metadata.keys())

    def count_blobs(self):
        """Return the number of unique content blobs stored."""
        return len(self._blobs)

    def clear(self):
        """Remove all artifacts (for testing / reset)."""
        self._blobs.clear()
        self._metadata.clear()
        if self._base.exists():
            shutil.rmtree(self._base)
            self._base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _compute_digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _blob_path(self, digest: str):
        return self._base / digest[:2] / digest
