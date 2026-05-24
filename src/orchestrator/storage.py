"""Blob Store — Content-addressed storage with digest-based deduplication."""

import hashlib
import time
from enum import Enum
from typing import Any, Dict, Optional


class DigestAlgorithm(Enum):
    SHA256 = "sha256"
    BLAKE2B = "blake2b"


class BlobMetadata:
    """Immutable metadata for a stored blob."""
    def __init__(self, digest: str, algorithm: DigestAlgorithm = DigestAlgorithm.SHA256,
                 logical_name: str = "", size_bytes: int = 0,
                 content_type: str = "application/octet-stream"):
        self.digest = digest
        self.algorithm = algorithm
        self.logical_name = logical_name
        self.size_bytes = size_bytes
        self.content_type = content_type
        self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "digest": self.digest,
            "algorithm": self.algorithm.value,
            "logical_name": self.logical_name,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BlobMetadata":
        meta = cls(
            digest=data["digest"],
            algorithm=DigestAlgorithm(data.get("algorithm", "sha256")),
            logical_name=data.get("logical_name", ""),
            size_bytes=data.get("size_bytes", 0),
            content_type=data.get("content_type", "application/octet-stream"),
        )
        meta.created_at = data.get("created_at", time.time())
        return meta


class ContentDigest:
    """Computes and verifies content digests."""
    @staticmethod
    def compute(data: bytes, algorithm: DigestAlgorithm = DigestAlgorithm.SHA256) -> str:
        if algorithm == DigestAlgorithm.SHA256:
            return hashlib.sha256(data).hexdigest()
        elif algorithm == DigestAlgorithm.BLAKE2B:
            return hashlib.blake2b(data).hexdigest()
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    @staticmethod
    def verify(data: bytes, expected_digest: str,
               algorithm: DigestAlgorithm = DigestAlgorithm.SHA256) -> bool:
        return ContentDigest.compute(data, algorithm) == expected_digest


class BlobStore:
    """Content-addressed blob store with digest-based deduplication."""

    def __init__(self):
        self._blobs: Dict[str, bytes] = {}
        self._metadata: Dict[str, BlobMetadata] = {}
        self._logical_index: Dict[str, str] = {}
        self._algorithm = DigestAlgorithm.SHA256

    def store(self, data: bytes, logical_name: str = "",
              content_type: str = "application/octet-stream") -> BlobMetadata:
        # Step 1: Compute digest BEFORE any dedup decision
        digest = ContentDigest.compute(data, self._algorithm)

        # Step 2: Check for suspicious metadata reuse
        if logical_name and logical_name in self._logical_index:
            existing_digest = self._logical_index[logical_name]
            if existing_digest != digest:
                raise ValueError(
                    f"Suspicious metadata reuse: logical_name '{logical_name}' "
                    f"previously mapped to digest '{existing_digest[:16]}...', "
                    f"but current content produces digest '{digest[:16]}...'. "
                    f"Review metadata integrity."
                )

        # Step 3: Deduplicate by content digest (not by logical metadata)
        if digest in self._blobs:
            meta = self._metadata[digest]
            if logical_name and logical_name not in self._logical_index:
                self._logical_index[logical_name] = digest
            return meta

        # Step 4: New blob
        self._blobs[digest] = data
        meta = BlobMetadata(
            digest=digest, algorithm=self._algorithm,
            logical_name=logical_name, size_bytes=len(data),
            content_type=content_type,
        )
        self._metadata[digest] = meta
        if logical_name:
            self._logical_index[logical_name] = digest
        return meta

    def get(self, digest: str) -> Optional[bytes]:
        return self._blobs.get(digest)

    def get_metadata(self, digest: str) -> Optional[BlobMetadata]:
        return self._metadata.get(digest)

    def get_by_name(self, logical_name: str) -> Optional[bytes]:
        digest = self._logical_index.get(logical_name)
        return self.get(digest) if digest else None

    def get_metadata_by_name(self, logical_name: str) -> Optional[BlobMetadata]:
        digest = self._logical_index.get(logical_name)
        return self.get_metadata(digest) if digest else None

    def has(self, digest: str) -> bool:
        return digest in self._blobs

    def count(self) -> int:
        return len(self._blobs)

    def list_digests(self) -> list:
        return list(self._blobs.keys())

    def verify_blob(self, digest: str) -> bool:
        data = self._blobs.get(digest)
        if data is None:
            return False
        return ContentDigest.verify(data, digest, self._algorithm)
