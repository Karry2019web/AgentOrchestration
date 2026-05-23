"""Structured logging configuration and audit trail."""

import json
import logging
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


class AuditTrail:
    """Records audit events for data access and operations."""

    def __init__(self):
        self._events: List[Dict[str, Any]] = []
        self._logger = logging.getLogger("audit")

    def record(
        self,
        action: str,
        actor: str,
        target_id: str,
        target_type: str,
        result: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": action,
            "actor": actor,
            "target_id": target_id,
            "target_type": target_type,
            "result": result,
            "metadata": metadata or {},
        }
        self._events.append(event)
        self._logger.info(json.dumps(event))
        return event

    def query(
        self,
        actor: Optional[str] = None,
        target_type: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        results = self._events
        if actor:
            results = [e for e in results if e["actor"] == actor]
        if target_type:
            results = [e for e in results if e["target_type"] == target_type]
        if action:
            results = [e for e in results if e["action"] == action]
        return results[-limit:]

    def clear(self) -> None:
        self._events.clear()


audit = AuditTrail()


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO), handlers=[handler]
    )
