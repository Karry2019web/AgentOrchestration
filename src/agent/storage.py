"""Cross-Region Artifact Reader — Handles replicated bucket reads with consistency guards."""

import hashlib
import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.common.errors import ArtifactNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_REPLICATION_WINDOW = 300
MAX_RETRY_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = [1, 2, 4, 8, 16]


class MetadataState(Enum):
    PENDING = "pending"
    AVAILABLE = "available"
    EXPIRED = "expired"
    PERMANENTLY_MISSING = "permanently_missing"


class ArtifactDigest:
    def __init__(self, artifact_id: str, sha256: str, size: int, region_origin: str):
        self.artifact_id = artifact_id
        self.sha256 = sha256
        self.size = size
        self.region_origin = region_origin
        self.created_at = time.time()

    def matches(self, other_sha256: str, other_size: int) -> bool:
        return self.sha256 == other_sha256 and self.size == other_size


class CrossRegionArtifactReader:
    def __init__(self, regions: List[str], replication_window: float = DEFAULT_REPLICATION_WINDOW, max_retries: int = MAX_RETRY_ATTEMPTS):
        self.regions = regions
        self.replication_window = replication_window
        self.max_retries = min(max_retries, len(RETRY_BACKOFF_SECONDS))
        self._digest_cache: Dict[str, ArtifactDigest] = {}
        self._metadata_store: Dict[str, Dict[str, Tuple[str, float]]] = {}
        self._in_memory_store: Dict[Tuple[str, str], bytes] = {}

    def read_artifact(self, artifact_id: str, target_region: str) -> bytes:
        digest = self._digest_cache.get(artifact_id)
        if digest is None:
            raise ArtifactNotFoundError(artifact_id=artifact_id, region=target_region, metadata_state=MetadataState.PERMANENTLY_MISSING.value)
        for attempt in range(1 + self.max_retries):
            metadata_state = self._check_metadata_state(artifact_id, target_region)
            if metadata_state in (MetadataState.PERMANENTLY_MISSING, MetadataState.EXPIRED):
                raise ArtifactNotFoundError(artifact_id=artifact_id, region=target_region, metadata_state=metadata_state.value)
            if metadata_state == MetadataState.AVAILABLE:
                data = self._fetch_artifact_bytes(artifact_id, target_region)
                if data is not None and self._verify_digest(data, digest):
                    return data
                logger.warning("Artifact %s digest mismatch in %s (attempt %d/%d)", artifact_id, target_region, attempt + 1, self.max_retries + 1)
            if attempt < self.max_retries:
                backoff = RETRY_BACKOFF_SECONDS[attempt]
                logger.info("Artifact %s not yet available in %s (state=%s). Retrying in %ds", artifact_id, target_region, metadata_state.value, backoff)
                time.sleep(backoff)
        state = self._check_metadata_state(artifact_id, target_region)
        raise ArtifactNotFoundError(artifact_id=artifact_id, region=target_region, metadata_state=f"{state.value} (retries exhausted)")

    def record_artifact(self, artifact_id: str, content: bytes, region_origin: str) -> ArtifactDigest:
        sha256 = hashlib.sha256(content).hexdigest()
        digest = ArtifactDigest(artifact_id=artifact_id, sha256=sha256, size=len(content), region_origin=region_origin)
        self._digest_cache[artifact_id] = digest
        self._update_metadata_state(artifact_id, region_origin, MetadataState.AVAILABLE)
        for region in self.regions:
            if region != region_origin:
                self._update_metadata_state(artifact_id, region, MetadataState.PENDING)
        return digest

    def acknowledge_replication(self, artifact_id: str, region: str) -> None:
        self._update_metadata_state(artifact_id, region, MetadataState.AVAILABLE)

    def expire_replication(self, artifact_id: str, region: str) -> None:
        self._update_metadata_state(artifact_id, region, MetadataState.EXPIRED)

    def _check_metadata_state(self, artifact_id: str, region: str) -> MetadataState:
        region_states = self._metadata_store.get(artifact_id, {})
        state_str, updated_at = region_states.get(region, (MetadataState.PERMANENTLY_MISSING.value, 0.0))
        if state_str == MetadataState.PENDING.value and time.time() - updated_at > self.replication_window:
            self._update_metadata_state(artifact_id, region, MetadataState.EXPIRED)
            return MetadataState.EXPIRED
        return MetadataState(state_str)

    def _update_metadata_state(self, artifact_id: str, region: str, state: MetadataState) -> None:
        if artifact_id not in self._metadata_store:
            self._metadata_store[artifact_id] = {}
        self._metadata_store[artifact_id][region] = (state.value, time.time())

    def _fetch_artifact_bytes(self, artifact_id: str, region: str) -> Optional[bytes]:
        return self._in_memory_store.get((artifact_id, region))

    def _verify_digest(self, data: bytes, digest: ArtifactDigest) -> bool:
        return digest.matches(hashlib.sha256(data).hexdigest(), len(data))

    def _get_replication_age(self, artifact_id: str, region: str) -> Optional[float]:
        region_states = self._metadata_store.get(artifact_id, {})
        _, updated_at = region_states.get(region, (None, None))
        if updated_at is not None:
            return time.time() - updated_at
        return None
