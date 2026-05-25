"""Data Lake Ingestion Pipeline — Purpose-limited writes with classification enforcement."""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from threading import Lock
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class DataClass(Enum):
    METRIC = "metric"
    LOG = "log"
    EVENT = "event"
    AUDIT = "audit"
    TASK_RESULT = "task_result"
    WORKFLOW_STATE = "workflow_state"
    CUSTOM = "custom"


class DestinationPolicy(Enum):
    STRICT = "strict"
    SHARED = "shared"
    PUBLIC = "public"


@dataclass
class PurposeManifest:
    purpose: str
    data_class: DataClass
    owner: str
    destination: str
    description: str = ""
    retention_days: int = 90
    tags: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["data_class"] = self.data_class.value
        return d


@dataclass
class DestinationPolicyRecord:
    name: str
    policy: DestinationPolicy
    allowed_data_classes: Set[DataClass]
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "policy": self.policy.value,
            "allowed_data_classes": [c.value for c in self.allowed_data_classes],
            "description": self.description,
        }


class DestinationNotFoundError(Exception):
    def __init__(self, destination: str):
        super().__init__(f"Destination not found in registry: {destination}")


class DataClassNotAllowedError(Exception):
    def __init__(self, data_class: DataClass, destination: str):
        super().__init__(
            f"Data class '{data_class.value}' is not approved for destination '{destination}'"
        )


class DataLakeWrite:
    def __init__(self, manifest: PurposeManifest, payload_size: int, success: bool, error: Optional[str] = None):
        self.timestamp = time.time()
        self.manifest = manifest
        self.payload_size = payload_size
        self.success = success
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "manifest": self.manifest.to_dict(),
            "payload_size": self.payload_size,
            "success": self.success,
            "error": self.error,
        }


class DataClassificationRegistry:
    def __init__(self):
        self._lock = Lock()
        self._destinations: Dict[str, DestinationPolicyRecord] = {}
        self._default_registration()

    def _default_registration(self) -> None:
        self.register(DestinationPolicyRecord(
            name="analytics_warehouse",
            policy=DestinationPolicy.SHARED,
            allowed_data_classes={DataClass.METRIC, DataClass.LOG, DataClass.AUDIT},
            description="Long-term analytical store.",
        ))
        self.register(DestinationPolicyRecord(
            name="operational_store",
            policy=DestinationPolicy.STRICT,
            allowed_data_classes={DataClass.EVENT, DataClass.TASK_RESULT, DataClass.WORKFLOW_STATE},
            description="Operational store — strict purpose binding.",
        ))
        self.register(DestinationPolicyRecord(
            name="data_marketplace",
            policy=DestinationPolicy.PUBLIC,
            allowed_data_classes={DataClass.CUSTOM, DataClass.METRIC},
            description="Public data marketplace.",
        ))

    def register(self, record: DestinationPolicyRecord) -> None:
        with self._lock:
            self._destinations[record.name] = record

    def get(self, destination: str) -> Optional[DestinationPolicyRecord]:
        with self._lock:
            return self._destinations.get(destination)

    def list_destinations(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [d.to_dict() for d in self._destinations.values()]

    def validate_write(self, manifest: PurposeManifest) -> None:
        record = self.get(manifest.destination)
        if record is None:
            raise DestinationNotFoundError(manifest.destination)
        if manifest.data_class not in record.allowed_data_classes:
            raise DataClassNotAllowedError(manifest.data_class, manifest.destination)


class IngestionPipeline:
    def __init__(self, registry: Optional[DataClassificationRegistry] = None):
        self.registry = registry or DataClassificationRegistry()
        self._audit_log: List[DataLakeWrite] = []
        self._lock = Lock()

    def write(self, manifest: PurposeManifest, payload: Any) -> Dict[str, Any]:
        payload_size = len(json.dumps(payload, default=str).encode("utf-8"))
        error = None
        success = False
        try:
            self.registry.validate_write(manifest)
            write_id = f"dl-{int(time.time())}-{hash(json.dumps(manifest.to_dict(), sort_keys=True)) & 0xffff}"
            success = True
            result: Dict[str, Any] = {
                "write_id": write_id,
                "status": "written",
                "payload_size_bytes": payload_size,
                "destination": manifest.destination,
            }
        except (DestinationNotFoundError, DataClassNotAllowedError) as e:
            error = str(e)
            result = {
                "status": "blocked",
                "error": error,
                "payload_size_bytes": payload_size,
                "destination": manifest.destination,
            }
        with self._lock:
            self._audit_log.append(DataLakeWrite(manifest, payload_size, success, error))
        return result

    def audit_report(self, purpose: Optional[str] = None, destination: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            results = list(self._audit_log)
        if purpose:
            results = [r for r in results if r.manifest.purpose == purpose]
        if destination:
            results = [r for r in results if r.manifest.destination == destination]
        return [r.to_dict() for r in results]

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._audit_log)
            ok = sum(1 for r in self._audit_log if r.success)
            blocked = total - ok
            total_bytes = sum(r.payload_size for r in self._audit_log if r.success)
            by_dest: Dict[str, int] = {}
            by_purpose: Dict[str, int] = {}
            for r in self._audit_log:
                by_dest[r.manifest.destination] = by_dest.get(r.manifest.destination, 0) + 1
                by_purpose[r.manifest.purpose] = by_purpose.get(r.manifest.purpose, 0) + 1
        return {
            "total_writes": total, "successful_writes": ok, "blocked_writes": blocked,
            "total_bytes_written": total_bytes,
            "writes_by_destination": by_dest, "writes_by_purpose": by_purpose,
        }


_data_lake_pipeline: Optional[IngestionPipeline] = None


def get_pipeline() -> IngestionPipeline:
    global _data_lake_pipeline
    if _data_lake_pipeline is None:
        _data_lake_pipeline = IngestionPipeline()
    return _data_lake_pipeline


def write_with_purpose(purpose: str, data_class: str, owner: str, destination: str, payload: Any, **kwargs) -> Dict[str, Any]:
    manifest = PurposeManifest(
        purpose=purpose, data_class=DataClass(data_class),
        owner=owner, destination=destination, **kwargs,
    )
    return get_pipeline().write(manifest, payload)

# 2026-05-25T02:52:06 update
