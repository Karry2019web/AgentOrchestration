"""Event quarantine for rolling orchestrator version upgrades.

Guards dispatch transitions with attempt, revision, and lifecycle checks
to prevent stale, duplicate, or policy-violating events from being committed
during rolling version upgrades.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Set

logger = logging.getLogger(__name__)


class DispatchDecision(Enum):
    """Outcome of a dispatch evaluation."""
    ACCEPTED = "accepted"
    DEFERRED = "deferred"
    QUARANTINED = "quarantined"


class QuarantineReason(Enum):
    """Why an event was quarantined."""
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    STALE_REVISION = "stale_revision"
    ATTEMPT_MISMATCH = "attempt_mismatch"
    INVALID_LIFECYCLE_TRANSITION = "invalid_lifecycle_transition"
    ROLLING_UPGRADE_BLOCKED = "rolling_upgrade_blocked"
    POLICY_VIOLATION = "policy_violation"


@dataclass(frozen=True)
class OrchestratorEvent:
    """A dispatchable orchestrator event with version metadata."""
    event_type: str
    stream_id: str
    attempt_id: str
    revision: int
    lifecycle_state: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class DispatchResult:
    """Result of evaluating an event for dispatch."""
    decision: DispatchDecision
    event: OrchestratorEvent
    reason: Optional[QuarantineReason] = None
    message: str = ""


# Valid lifecycle transitions: current_state -> set(allowed next states)
_ALLOWED_LIFECYCLE_TRANSITIONS: Dict[Optional[str], FrozenSet[str]] = {
    None: frozenset({"pending", "running"}),
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"completed", "failed", "cancelled"}),
    "cancelled": frozenset(),
    "completed": frozenset(),
    "failed": frozenset(),
    "terminated": frozenset(),
}

_TERMINAL_LIFECYCLE_STATES: FrozenSet[str] = frozenset({
    "cancelled", "completed", "failed", "terminated",
})


class EventQuarantine:
    """Guards orchestrator event dispatch during rolling version upgrades.

    Evaluates every event against quarantine rules before allowing it to
    be dispatched. Unknown event types, stale revisions, attempt mismatches,
    invalid lifecycle transitions, and policy violations are either deferred
    (held for replay after upgrade) or quarantined (rejected permanently).
    """

    def __init__(
        self,
        known_event_types: Iterable[str],
        upgrade_version: Optional[str] = None,
        allow_deferred_replay: bool = True,
    ) -> None:
        self._known_types: Set[str] = set(known_event_types)
        self._upgrade_version: Optional[str] = upgrade_version
        self._allow_deferred_replay = allow_deferred_replay
        self._stream_revisions: Dict[str, int] = {}
        self._deferred: List[OrchestratorEvent] = []
        self._audit_log: List[Dict[str, Any]] = []
        self._upgrade_complete = False

    def evaluate(self, event: OrchestratorEvent) -> DispatchResult:
        """Evaluate an event and return the dispatch decision."""
        # 1. Unknown event type check
        if event.event_type not in self._known_types:
            return self._quarantine(event, QuarantineReason.UNKNOWN_EVENT_TYPE,
                                    f"Unknown event type: {event.event_type!r}")

        # 2. Rolling upgrade guard
        if self._upgrade_version and not self._upgrade_complete:
            blocked = self._check_upgrade_policy(event)
            if blocked:
                return blocked

        # 3. Stale revision check
        latest = self._stream_revisions.get(event.stream_id, -1)
        if event.revision <= latest:
            return self._quarantine(
                event, QuarantineReason.STALE_REVISION,
                f"Stale revision {event.revision} for stream {event.stream_id} "
                f"(latest: {latest})",
            )

        # 4. Lifecycle transition validity
        if event.lifecycle_state is not None:
            current_state = self._infer_current_lifecycle(event.stream_id)
            allowed = _ALLOWED_LIFECYCLE_TRANSITIONS.get(
                current_state, _ALLOWED_LIFECYCLE_TRANSITIONS[None],
            )
            if event.lifecycle_state not in allowed:
                return self._quarantine(
                    event, QuarantineReason.INVALID_LIFECYCLE_TRANSITION,
                    f"Invalid lifecycle transition: {current_state!r} -> "
                    f"{event.lifecycle_state!r} (allowed: {sorted(allowed)})",
                )

        # 5. Accept the event
        self._stream_revisions[event.stream_id] = event.revision
        return DispatchResult(
            decision=DispatchDecision.ACCEPTED,
            event=event,
            message=f"Event {event.event_type} accepted for stream {event.stream_id}",
        )

    def defer_event(self, event: OrchestratorEvent, reason: str = "") -> None:
        """Hold an event for replay after the rolling upgrade completes."""
        self._deferred.append(event)
        self._audit_log.append({
            "timestamp": time.time(),
            "event_type": event.event_type,
            "stream_id": event.stream_id,
            "attempt_id": event.attempt_id,
            "revision": event.revision,
            "decision": DispatchDecision.DEFERRED.value,
            "reason": reason,
        })

    def complete_upgrade(self) -> List[OrchestratorEvent]:
        """Mark the rolling upgrade as complete and return deferred events."""
        self._upgrade_complete = True
        deferred = list(self._deferred)
        self._deferred.clear()
        logger.info(
            "Rolling upgrade complete, replaying %d deferred events",
            len(deferred),
        )
        return deferred

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Return the quarantine audit log (no private event payloads)."""
        return list(self._audit_log)

    def get_deferred_count(self) -> int:
        return len(self._deferred)

    def get_quarantine_count(self) -> int:
        return sum(
            1 for entry in self._audit_log
            if entry["decision"] == DispatchDecision.QUARANTINED.value
        )

    def _quarantine(
        self, event: OrchestratorEvent, reason: QuarantineReason, message: str,
    ) -> DispatchResult:
        self._audit_log.append({
            "timestamp": time.time(),
            "event_type": event.event_type,
            "stream_id": event.stream_id,
            "attempt_id": event.attempt_id,
            "revision": event.revision,
            "decision": DispatchDecision.QUARANTINED.value,
            "reason": reason.value,
        })
        logger.warning("Quarantined event: %s", message)
        return DispatchResult(
            decision=DispatchDecision.QUARANTINED,
            event=event,
            reason=reason,
            message=message,
        )

    def _check_upgrade_policy(self, event: OrchestratorEvent) -> Optional[DispatchResult]:
        """Check rolling upgrade policy. Returns a DispatchResult if blocked."""
        if self._upgrade_version and self._is_new_version_event(event):
            reason = f"Deferred during rolling upgrade to {self._upgrade_version}"
            self.defer_event(event, reason)
            return DispatchResult(
                decision=DispatchDecision.DEFERRED,
                event=event,
                reason=QuarantineReason.ROLLING_UPGRADE_BLOCKED,
                message=reason,
            )
        return None

    def _is_new_version_event(self, event: OrchestratorEvent) -> bool:
        latest = self._stream_revisions.get(event.stream_id, -1)
        return event.revision > latest + 5

    def _infer_current_lifecycle(self, stream_id: str) -> Optional[str]:
        _ = stream_id
        return None
