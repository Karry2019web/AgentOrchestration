"""Audit reporter — logs and exposes data lake ingestion records."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .classification import DataClass
from .lake import IngestionManifest, IngestionResult, IngestionStatus


@dataclass
class AuditEntry:
    """A single audit record for a data lake write."""
    entry_id: str = field(default_factory=lambda: str(uuid4()))
    manifest_id: str = ""
    purpose: str = ""
    data_class: str = ""
    destination: str = ""
    owner: str = ""
    status: str = ""
    reason: str = ""
    record_count: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: Dict[str, str] = field(default_factory=dict)


class AuditReporter:
    """Generates audit reports from ingestion results."""

    def __init__(self):
        self._entries: List[AuditEntry] = []

    def record(self, manifest: IngestionManifest, result: IngestionResult) -> AuditEntry:
        entry = AuditEntry(
            manifest_id=manifest.manifest_id,
            purpose=manifest.purpose,
            data_class=manifest.data_class.value,
            destination=manifest.destination,
            owner=manifest.owner,
            status=result.status.value,
            reason=result.reason,
            record_count=manifest.record_count,
            tags=dict(manifest.tags),
        )
        self._entries.append(entry)
        return entry

    def report_by_purpose(self, purpose: str) -> List[AuditEntry]:
        return [e for e in self._entries if e.purpose == purpose]

    def report_by_owner(self, owner: str) -> List[AuditEntry]:
        return [e for e in self._entries if e.owner == owner]

    def report_by_data_class(self, data_class: DataClass) -> List[AuditEntry]:
        return [e for e in self._entries if e.data_class == data_class.value]

    def report_by_destination(self, destination: str) -> List[AuditEntry]:
        return [e for e in self._entries if e.destination == destination]

    def full_report(self) -> List[AuditEntry]:
        return list(self._entries)

    def summary(self) -> Dict[str, Any]:
        """Aggregate summary grouped by destination and purpose."""
        by_dest: Dict[str, int] = {}
        by_purpose: Dict[str, int] = {}
        accepted = rejected = 0
        for e in self._entries:
            by_dest[e.destination] = by_dest.get(e.destination, 0) + 1
            by_purpose[e.purpose] = by_purpose.get(e.purpose, 0) + 1
            if e.status == IngestionStatus.APPROVED.value:
                accepted += 1
            elif e.status == IngestionStatus.REJECTED.value:
                rejected += 1
        return {
            "total_entries": len(self._entries),
            "accepted": accepted,
            "rejected": rejected,
            "by_destination": by_dest,
            "by_purpose": by_purpose,
        }
