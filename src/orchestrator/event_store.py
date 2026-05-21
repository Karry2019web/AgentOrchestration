"""Event retention store — separate operational logs from audit records."""

import datetime
import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventSeverity(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class EventRecord:
    """A single event record for either store."""
    event_id: str
    timestamp: str
    source: str
    event_type: str
    severity: EventSeverity
    payload: Dict[str, Any]
    digest: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "event_type": self.event_type,
            "severity": self.severity.value,
            "payload": self.payload,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventRecord":
        return cls(
            event_id=data["event_id"],
            timestamp=data["timestamp"],
            source=data["source"],
            event_type=data["event_type"],
            severity=EventSeverity(data.get("severity", "info")),
            payload=data.get("payload", {}),
            digest=data.get("digest", ""),
        )


class OperationalStore:
    """Compactable operational log store.

    Operational logs can be pruned or compacted over time.
    Writes are tracked by sequence number for ordered replay.
    """

    def __init__(self, max_records: int = 10000):
        self._records: List[EventRecord] = []
        self._max_records = max_records
        self._lock = threading.Lock()
        self._sequence = 0

    def write(self, record: EventRecord) -> int:
        with self._lock:
            self._sequence += 1
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records.pop(0)
            return self._sequence

    def read(self, limit: int = 100, offset: int = 0) -> List[EventRecord]:
        with self._lock:
            return list(self._records[offset:offset + limit])

    def compact(self, before_timestamp: str) -> int:
        """Remove operational records older than the given timestamp.
        Returns the number of removed records.
        """
        with self._lock:
            before = len(self._records)
            self._records = [r for r in self._records if r.timestamp >= before_timestamp]
            removed = before - len(self._records)
            if removed:
                logger.info(f"OperationalStore: compacted {removed} records older than {before_timestamp}")
            return removed

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._sequence = 0


class AuditStore:
    """Append-only audit record store with chained SHA-256 digests.

    Audit records cannot be deleted or modified once written.
    Each record carries a digest of its own content chained to the
    previous record's digest, forming an immutable chain.
    """

    def __init__(self):
        self._records: List[EventRecord] = []
        self._lock = threading.Lock()
        self._last_digest = ""

    def _compute_digest(self, record: EventRecord) -> str:
        content = json.dumps(record.to_dict(), sort_keys=True, default=str)
        h = hashlib.sha256(content.encode("utf-8"))
        h.update(self._last_digest.encode("utf-8"))
        return h.hexdigest()

    def append(self, record: EventRecord) -> str:
        with self._lock:
            record.digest = self._compute_digest(record)
            self._records.append(record)
            self._last_digest = record.digest
            return record.digest

    def read(self, limit: int = 100, offset: int = 0) -> List[EventRecord]:
        with self._lock:
            return list(self._records[offset:offset + limit])

    def verify_chain(self) -> bool:
        """Verify the integrity of the entire audit chain."""
        with self._lock:
            prev_digest = ""
            for record in self._records:
                stored_digest = record.digest
                record.digest = ""
                content = json.dumps(record.to_dict(), sort_keys=True, default=str)
                h = hashlib.sha256(content.encode("utf-8"))
                h.update(prev_digest.encode("utf-8"))
                expected = h.hexdigest()
                if stored_digest != expected:
                    logger.error(f"AuditStore: chain broken at {record.event_id}")
                    return False
                record.digest = stored_digest
                prev_digest = stored_digest
            return True

    def count(self) -> int:
        with self._lock:
            return len(self._records)


class EventRetentionStore:
    """High-level store that routes events to operational and audit stores.

    - Operational events: written to OperationalStore (compactable)
    - Audit events: written to AuditStore (append-only, chained digests)
    - Cleanup operations only affect the operational store
    """

    def __init__(self, max_operational_records: int = 10000):
        self.operational = OperationalStore(max_records=max_operational_records)
        self.audit = AuditStore()

    def write_operational(self, record: EventRecord) -> int:
        """Write an operational log event. Returns sequence number."""
        return self.operational.write(record)

    def write_audit(self, record: EventRecord) -> str:
        """Write an audit record (append-only with digest chaining). Returns digest."""
        return self.audit.append(record)

    def write_event(
        self,
        event_id: str,
        source: str,
        event_type: str,
        payload: Dict[str, Any],
        severity: EventSeverity = EventSeverity.INFO,
        audit: bool = False,
    ) -> None:
        """Write an event to either or both stores."""
        timestamp = datetime.datetime.utcnow().isoformat() + "Z"
        record = EventRecord(
            event_id=event_id,
            timestamp=timestamp,
            source=source,
            event_type=event_type,
            severity=severity,
            payload=payload,
        )
        self.write_operational(record)
        if audit:
            self.write_audit(record)

    def compact_operational(self, before_timestamp: str) -> int:
        """Compact operational logs. Audit records are never affected."""
        return self.operational.compact(before_timestamp)

    def verify_audit_chain(self) -> bool:
        """Verify the integrity of the audit chain."""
        return self.audit.verify_chain()

    def get_stats(self) -> Dict[str, int]:
        return {
            "operational_count": self.operational.count(),
            "audit_count": self.audit.count(),
        }
