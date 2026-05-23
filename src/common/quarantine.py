"""Quarantine Store — Failed validation payload retention and redaction."""

import time
import logging
from typing import Any, Dict, List, Optional
from threading import RLock
from uuid import uuid4

logger = logging.getLogger(__name__)


class QuarantineStore:
    """Stores failed validation payloads with retention, access controls, and redaction.

    Each quarantined record has an expiration timestamp. Expired records are
    removed by the cleanup sweep. Debug views return redacted summaries
    instead of raw payloads by default.
    """

    def __init__(self, retention_seconds: int = 86400 * 7):
        self._lock = RLock()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._retention_seconds = retention_seconds

    def set_retention(self, seconds: int) -> None:
        with self._lock:
            self._retention_seconds = seconds

    def get_retention(self) -> int:
        with self._lock:
            return self._retention_seconds

    def store(self, payload: Dict[str, Any], task_id: Optional[str] = None) -> str:
        record_id = str(uuid4())
        now = time.time()
        with self._lock:
            self._records[record_id] = {
                "id": record_id,
                "task_id": task_id or "",
                "payload": payload,
                "created_at": now,
                "expires_at": now + self._retention_seconds,
                "reason": payload.get("error", payload.get("reason", "validation_failed")),
            }
        logger.info("Quarantined record %s (expires at %s)", record_id,
                     self._records[record_id]["expires_at"])
        return record_id

    def get_raw(self, record_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._records.get(record_id)
            if not record:
                return None
            if record["expires_at"] <= time.time():
                self._records.pop(record_id, None)
                return None
            return dict(record)

    def get_redacted(self, record_id: str) -> Optional[Dict[str, Any]]:
        raw = self.get_raw(record_id)
        if not raw:
            return None
        return self._redact(raw)

    def _redact(self, record: Dict[str, Any]) -> Dict[str, Any]:
        payload = record.get("payload", {})
        return {
            "id": record["id"],
            "task_id": record["task_id"],
            "reason": record["reason"],
            "created_at": record["created_at"],
            "expires_at": record["expires_at"],
            "summary": {
                "type": payload.get("type", "unknown"),
                "field_count": len(payload) if isinstance(payload, dict) else 1,
                "data": "[REDACTED — use /quarantine/{id}/raw for full payload]",
            },
        }

    def list_redacted(self, limit: int = 50) -> List[Dict[str, Any]]:
        self.cleanup()
        with self._lock:
            all_records = list(self._records.values())
            all_records.sort(key=lambda r: r["created_at"], reverse=True)
            return [self._redact(r) for r in all_records[:limit]]

    def count(self) -> int:
        self.cleanup()
        with self._lock:
            return len(self._records)

    def cleanup(self) -> int:
        now = time.time()
        purged = 0
        with self._lock:
            expired = [rid for rid, rec in self._records.items()
                       if rec["expires_at"] <= now]
            for rid in expired:
                del self._records[rid]
                purged += 1
        if purged:
            logger.info("Quarantine cleanup: purged %d expired records", purged)
        return purged


quarantine_store = QuarantineStore()
