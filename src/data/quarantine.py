"""Quarantine Store — Retention-managed storage for failed validation payloads."""

import json
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Default retention: 7 days
DEFAULT_RETENTION_SECONDS = 7 * 24 * 3600


@dataclass
class QuarantineRecord:
    """A single quarantined validation failure payload."""

    id: str = field(default_factory=lambda: str(uuid4()))
    payload: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    source: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + DEFAULT_RETENTION_SECONDS)
    redacted: bool = False

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_redacted_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "error": self.error,
            "source": self.source,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "redacted": True,
            "payload_summary": self._summarize_payload(),
        }

    def _summarize_payload(self) -> str:
        if not self.payload:
            return "(empty)"
        keys = list(self.payload.keys())
        preview = {k: str(self.payload[k])[:50] for k in keys[:3]}
        extra = f" and {len(keys) - 3} more fields" if len(keys) > 3 else ""
        return f"{{{', '.join(f'{k}: {v}' for k, v in preview.items())}{extra}}}"


class QuarantineStore:
    """In-memory quarantine store with TTL-based expiration and redacted debug views."""

    def __init__(self, retention_seconds: int = DEFAULT_RETENTION_SECONDS):
        self._records: Dict[str, QuarantineRecord] = {}
        self._retention_seconds = retention_seconds

    @property
    def retention_seconds(self) -> int:
        return self._retention_seconds

    @retention_seconds.setter
    def retention_seconds(self, value: int) -> None:
        self._retention_seconds = value

    def store(self, payload: Dict[str, Any], error: str, source: str = "") -> str:
        """Store a failed validation payload. Returns the record ID."""
        record = QuarantineRecord(
            payload=payload,
            error=error,
            source=source,
            expires_at=time.time() + self._retention_seconds,
        )
        self._records[record.id] = record
        logger.info(
            "Quarantined validation failure %s from %s (expires %.0f)",
            record.id, source or "unknown", record.expires_at,
        )
        return record.id

    def get(self, record_id: str) -> Optional[QuarantineRecord]:
        record = self._records.get(record_id)
        if record is None:
            return None
        if record.is_expired():
            self._records.pop(record_id, None)
            return None
        return record

    def list_raw(self) -> List[Dict[str, Any]]:
        """Return all non-expired records with full payloads (internal use)."""
        self._clean_expired()
        return [r.to_dict() for r in self._records.values()]

    def list_redacted(self) -> List[Dict[str, Any]]:
        """Return all non-expired records as redacted summaries (debug views)."""
        self._clean_expired()
        return [r.to_redacted_dict() for r in self._records.values()]

    def clean_expired(self) -> int:
        """Remove all expired records. Returns count removed."""
        return self._clean_expired()

    def _clean_expired(self) -> int:
        now = time.time()
        expired = [rid for rid, rec in self._records.items() if now > rec.expires_at]
        for rid in expired:
            del self._records[rid]
        if expired:
            logger.info("Cleaned %d expired quarantine records", len(expired))
        return len(expired)

    def count(self) -> int:
        self._clean_expired()
        return len(self._records)

    def get_retention_config(self) -> Dict[str, Any]:
        return {
            "retention_seconds": self._retention_seconds,
            "retention_days": self._retention_seconds / 86400,
            "active_records": self.count(),
        }


# Module-level singleton for convenience
_default_store: Optional[QuarantineStore] = None


def get_store(retention_seconds: Optional[int] = None) -> QuarantineStore:
    global _default_store
    if _default_store is None:
        _default_store = QuarantineStore(
            retention_seconds=retention_seconds or DEFAULT_RETENTION_SECONDS,
        )
    return _default_store
