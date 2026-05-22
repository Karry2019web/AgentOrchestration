"""Artifact storage class tracking and lifecycle management."""

import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class StorageClass(Enum):
    """Supported storage classes with performance tiers."""
    STANDARD = "standard"        # Fast, hot storage
    NEARLINE = "nearline"        # Low-frequency access
    COLDLINE = "coldline"        # Cold storage
    ARCHIVE = "archive"          # Archival storage, slowest retrieval


# Retrieval latency estimates in seconds for each storage class
STORAGE_CLASS_LATENCY: Dict[StorageClass, float] = {
    StorageClass.STANDARD: 0.01,
    StorageClass.NEARLINE: 5.0,
    StorageClass.COLDLINE: 30.0,
    StorageClass.ARCHIVE: 300.0,
}

# Storage cost multiplier relative to STANDARD (lower is cheaper)
STORAGE_CLASS_COST: Dict[StorageClass, float] = {
    StorageClass.STANDARD: 1.0,
    StorageClass.NEARLINE: 0.5,
    StorageClass.COLDLINE: 0.25,
    StorageClass.ARCHIVE: 0.10,
}

# Ordered list for lifecycle transitions (forward = colder)
STORAGE_CLASS_TIER = list(StorageClass)


@dataclass
class ArtifactMetadata:
    """Metadata for a single artifact, including storage class tracking."""
    artifact_id: str
    name: str
    current_class: StorageClass = StorageClass.STANDARD
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    transitions: List[Dict] = field(default_factory=list)

    def record_transition(self, to_class: StorageClass, reason: str = "lifecycle") -> None:
        """Record a storage class transition."""
        self.transitions.append({
            "from": self.current_class.value,
            "to": to_class.value,
            "timestamp": time.time(),
            "reason": reason,
        })
        self.current_class = to_class
        self.updated_at = time.time()

    def retrieval_latency_seconds(self) -> float:
        """Estimated retrieval latency based on current storage class."""
        return STORAGE_CLASS_LATENCY.get(self.current_class, 0.01)

    def current_cost_multiplier(self) -> float:
        """Current storage cost multiplier."""
        return STORAGE_CLASS_COST.get(self.current_class, 1.0)

    def is_slow_storage(self) -> bool:
        """True if the artifact is in a slow (non-standard) storage class."""
        return self.current_class != StorageClass.STANDARD

    def to_dict(self) -> Dict:
        """Serialize to dictionary for reporting."""
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "current_storage_class": self.current_class.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "retrieval_latency_seconds": self.retrieval_latency_seconds(),
            "cost_multiplier": self.current_cost_multiplier(),
            "is_slow_storage": self.is_slow_storage(),
            "transition_count": len(self.transitions),
            "transitions": self.transitions[-10:],  # last 10 transitions
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ArtifactMetadata":
        """Deserialize from dictionary."""
        meta = cls(
            artifact_id=data["artifact_id"],
            name=data.get("name", ""),
            current_class=StorageClass(data["current_storage_class"]),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            transitions=data.get("transitions", []),
        )
        return meta


class LifecycleSync:
    """Simulates object storage lifecycle rule evaluation and transition sync."""

    def __init__(self, cold_after_days: int = 30, archive_after_days: int = 90):
        self.cold_after_days = cold_after_days
        self.archive_after_days = archive_after_days
        self._last_sync: Optional[float] = None

    def evaluate(self, artifact: ArtifactMetadata) -> Optional[StorageClass]:
        """Evaluate what storage class an artifact should be in based on age.

        Returns the target storage class if a transition is needed, None otherwise.
        """
        age_days = (time.time() - artifact.updated_at) / 86400

        if age_days >= self.archive_after_days:
            target = StorageClass.ARCHIVE
        elif age_days >= self.cold_after_days:
            target = StorageClass.COLDLINE
        else:
            return None

        # Only transition if the target is colder than the current tier
        current_idx = STORAGE_CLASS_TIER.index(artifact.current_class)
        target_idx = STORAGE_CLASS_TIER.index(target)
        if target_idx > current_idx:
            return target
        return None

    def run_sync(self, artifacts: List[ArtifactMetadata]) -> List[Tuple[ArtifactMetadata, StorageClass]]:
        """Run lifecycle sync on a list of artifacts. Returns transitions applied."""
        transitions: List[Tuple[ArtifactMetadata, StorageClass]] = []
        for artifact in artifacts:
            target = self.evaluate(artifact)
            if target is not None:
                artifact.record_transition(target, reason="lifecycle_sync")
                transitions.append((artifact, target))
                logger.info(
                    "Lifecycle sync: %s transitioned from %s to %s",
                    artifact.artifact_id, artifact.current_class.value, target.value,
                )
        self._last_sync = time.time()
        return transitions

    @property
    def last_sync(self) -> Optional[float]:
        return self._last_sync


class ArtifactStorage:
    """Manages artifact metadata, storage class tracking, and lifecycle transitions."""

    def __init__(self):
        self._artifacts: Dict[str, ArtifactMetadata] = {}
        self._lifecycle = LifecycleSync()

    def register(self, artifact_id: str, name: str,
                 initial_class: StorageClass = StorageClass.STANDARD) -> ArtifactMetadata:
        """Register a new artifact in the storage system."""
        if artifact_id in self._artifacts:
            raise ValueError(f"Artifact {artifact_id} already registered")

        meta = ArtifactMetadata(
            artifact_id=artifact_id,
            name=name,
            current_class=initial_class,
        )
        self._artifacts[artifact_id] = meta
        logger.info("Artifact registered: %s (%s) in %s", artifact_id, name, initial_class.value)
        return meta

    def get(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """Get artifact metadata, with a slow-storage warning."""
        meta = self._artifacts.get(artifact_id)
        if meta and meta.is_slow_storage():
            logger.warning(
                "Artifact %s is in %s storage (retrieval latency: %.1fs)",
                artifact_id, meta.current_class.value, meta.retrieval_latency_seconds(),
            )
        return meta

    def record_transition(self, artifact_id: str, to_class: StorageClass,
                          reason: str = "explicit") -> bool:
        """Record a storage class transition for an artifact."""
        meta = self._artifacts.get(artifact_id)
        if not meta:
            logger.error("Artifact not found: %s", artifact_id)
            return False
        meta.record_transition(to_class, reason)
        return True

    def report(self, include_slow_warning: bool = True) -> List[Dict]:
        """Generate a storage class report for all artifacts."""
        report = [meta.to_dict() for meta in self._artifacts.values()]
        if include_slow_warning:
            for entry in report:
                if entry["is_slow_storage"]:
                    entry["warning"] = (
                        f"Artifact in {entry['current_storage_class']} storage. "
                        f"Estimated retrieval latency: {entry['retrieval_latency_seconds']:.1f}s."
                    )
        return report

    def run_lifecycle_sync(self) -> List[Tuple[ArtifactMetadata, StorageClass]]:
        """Run the lifecycle transition sync on all artifacts."""
        return self._lifecycle.run_sync(list(self._artifacts.values()))

    def list_slow_artifacts(self) -> List[ArtifactMetadata]:
        """List artifacts in slow (non-standard) storage with warnings."""
        return [a for a in self._artifacts.values() if a.is_slow_storage()]

    @property
    def lifecycle(self) -> LifecycleSync:
        return self._lifecycle

    def count(self) -> int:
        return len(self._artifacts)
