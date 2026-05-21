"""Purpose-governed data lake ingestion with classification registry."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Dict, Iterable, List, Optional, Set


class PolicyError(ValueError):
    """Raised when a write violates purpose or classification policy."""


@dataclass(frozen=True)
class Manifest:
    purpose: str
    classification: str
    owner: str
    destination: str


@dataclass
class AuditEntry:
    key: str
    purpose: str
    classification: str
    destination: str
    approved: bool
    reason: str
    timestamp: float
    owner: str


class ClassificationRegistry:
    """Registry mapping destinations to allowed data classifications.

    Each destination declares which classifications it is approved for.
    """

    def __init__(self):
        self._policies: Dict[str, Set[str]] = {}
        self._lock = RLock()

    def allow(self, destination: str, *classifications: str) -> None:
        """Register a destination with the set of approved classifications."""
        for c in classifications:
            self._validate_not_blank("classification", c)
        self._validate_not_blank("destination", destination)
        with self._lock:
            approved = self._policies.setdefault(destination.strip().lower(), set())
            approved.update(c.strip().lower() for c in classifications)

    def check(self, destination: str, classification: str) -> bool:
        self._validate_not_blank("classification", classification)
        """Return True if *classification* is approved for *destination*."""
        with self._lock:
            allowed = self._policies.get(destination.strip().lower())
            if allowed is None:
                return False
            return classification.strip().lower() in allowed

    @staticmethod
    def _validate_not_blank(field_name: str, value: str) -> None:
        if not value or not value.strip():
            raise PolicyError(f"{field_name} must not be blank")


class GovernedPipeline:
    """Ingestion pipeline that enforces purpose + classification policies.

    Every write requires a ``Manifest`` declaring the purpose, data
    classification, owner, and intended destination.  If the destination's
    policy does not allow the classification, the write is rejected with a
    ``PolicyError``.  Accepted writes are recorded as ``AuditEntry`` objects
    for downstream reporting.
    """

    def __init__(self, registry: ClassificationRegistry):
        self._registry = registry
        self._lock = RLock()
        self._store: Dict[str, Any] = {}
        self._audit: List[AuditEntry] = []

    def write(self, key: str, data: Any, manifest: Manifest) -> AuditEntry:
        """Write *data* under *key* with governance checks.

        Returns an ``AuditEntry`` recording the approval decision.
        """
        self._validate_not_blank("key", key)
        self._validate_not_blank("purpose", manifest.purpose)
        self._validate_not_blank("classification", manifest.classification)
        self._validate_not_blank("owner", manifest.owner)
        self._validate_not_blank("destination", manifest.destination)

        if not self._registry.check(manifest.destination,
                                    manifest.classification):
            entry = AuditEntry(
                key=key,
                purpose=manifest.purpose,
                classification=manifest.classification,
                destination=manifest.destination,
                approved=False,
                reason=f"destination '{manifest.destination}' does not allow "
                       f"classification '{manifest.classification}'",
                timestamp=time.time(),
                owner=manifest.owner,
            )
            with self._lock:
                self._audit.append(entry)
            raise PolicyError(entry.reason)

        with self._lock:
            self._store[key] = data
            entry = AuditEntry(
                key=key,
                purpose=manifest.purpose,
                classification=manifest.classification,
                destination=manifest.destination,
                approved=True,
                reason="policy approved",
                timestamp=time.time(),
                owner=manifest.owner,
            )
            self._audit.append(entry)

        return entry

    def read(self, key: str) -> Optional[Any]:
        with self._lock:
            return self._store.get(key)

    def list_audit(self,
                   purpose: Optional[str] = None,
                   owner: Optional[str] = None,
                   limit: int = 50) -> List[Dict[str, Any]]:
        """Return audit entries, optionally filtered."""
        with self._lock:
            results = []
            for e in self._audit:
                if purpose and e.purpose != purpose:
                    continue
                if owner and e.owner != owner:
                    continue
                results.append({
                    "key": e.key,
                    "classification": e.classification,
                    "destination": e.destination,
                    "approved": e.approved,
                    "reason": e.reason,
                    "timestamp": e.timestamp,
                    "owner": e.owner,
                })
                if len(results) >= limit:
                    break
            return results

    @staticmethod
    def _validate_not_blank(field_name: str, value: str) -> None:
        if not value or not value.strip():
            raise PolicyError(f"{field_name} must not be blank")
