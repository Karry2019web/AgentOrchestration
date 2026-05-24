"""Data lake ingestion pipeline — purpose-scoped writes with destination validation."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .classification import DataClass, DataClassificationRegistry

logger = logging.getLogger(__name__)


class IngestionStatus(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"


@dataclass
class IngestionManifest:
    """Metadata accompanying every data lake write."""
    purpose: str
    data_class: DataClass
    owner: str
    destination: str
    payload_summary: str = ""
    source: str = ""
    record_count: int = 0
    tags: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    manifest_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class IngestionResult:
    """Outcome of an ingestion attempt."""
    manifest_id: str
    status: IngestionStatus
    destination: str
    data_class: DataClass
    reason: str = ""
    approved_destinations: List[str] = field(default_factory=list)


class DataLakeIngestor:
    """Ingests data into the data lake with purpose and classification enforcement."""

    def __init__(self, registry: Optional[DataClassificationRegistry] = None):
        self._registry = registry or DataClassificationRegistry()
        self._ingested: List[IngestionResult] = []

    @property
    def registry(self) -> DataClassificationRegistry:
        return self._registry

    def ingest(self, manifest: IngestionManifest) -> IngestionResult:
        """Attempt to ingest data. Fails if destination is not approved for the data class."""
        result = self._validate(manifest)

        if result.status == IngestionStatus.APPROVED:
            logger.info(
                "Ingestion approved: purpose=%s data_class=%s destination=%s owner=%s",
                manifest.purpose, manifest.data_class.value, manifest.destination, manifest.owner,
            )
            self._ingested.append(result)
        else:
            logger.warning(
                "Ingestion rejected: purpose=%s data_class=%s destination=%s reason=%s",
                manifest.purpose, manifest.data_class.value, manifest.destination, result.reason,
            )

        return result

    def ingest_batch(self, manifests: List[IngestionManifest]) -> List[IngestionResult]:
        return [self.ingest(m) for m in manifests]

    def _validate(self, manifest: IngestionManifest) -> IngestionResult:
        if not manifest.purpose or not manifest.purpose.strip():
            return IngestionResult(
                manifest_id=manifest.manifest_id,
                status=IngestionStatus.REJECTED,
                destination=manifest.destination,
                data_class=manifest.data_class,
                reason="Purpose metadata is required but was empty",
            )

        if not self._registry.is_destination_allowed(manifest.destination, manifest.data_class):
            allowed = self._registry.list_destinations_for_class(manifest.data_class)
            return IngestionResult(
                manifest_id=manifest.manifest_id,
                status=IngestionStatus.REJECTED,
                destination=manifest.destination,
                data_class=manifest.data_class,
                reason=(
                    f"Destination '{manifest.destination}' is not approved "
                    f"for data class '{manifest.data_class.value}'. "
                    f"Approved destinations: {allowed}"
                ),
                approved_destinations=allowed,
            )

        return IngestionResult(
            manifest_id=manifest.manifest_id,
            status=IngestionStatus.APPROVED,
            destination=manifest.destination,
            data_class=manifest.data_class,
            reason="Approved by policy",
            approved_destinations=[manifest.destination],
        )

    def get_history(self) -> List[IngestionResult]:
        return list(self._ingested)
