"""Audit trail — Records export download events with actor, export ID, timestamp, and result."""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditTrail:
    """In-memory audit trail for export download events."""

    def __init__(self):
        self._events: List[Dict] = []

    def record_download(
        self,
        actor: str,
        export_id: str,
        success: bool,
        error: Optional[str] = None,
    ) -> Dict:
        event = {
            "id": str(uuid.uuid4()),
            "event": "export.download",
            "actor": actor,
            "export_id": export_id,
            "timestamp": _now_iso(),
            "success": success,
            "error": error,
        }
        self._events.append(event)
        return event

    def get_events(
        self,
        export_id: Optional[str] = None,
        actor: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        result = self._events[:]
        if export_id:
            result = [e for e in result if e["export_id"] == export_id]
        if actor:
            result = [e for e in result if e["actor"] == actor]
        result.reverse()
        return result[:limit]

    def latest_event(self) -> Optional[Dict]:
        if not self._events:
            return None
        return self._events[-1]

    def clear(self) -> None:
        self._events.clear()


audit_trail = AuditTrail()
