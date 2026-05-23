"""Event Quarantine — Reject unknown event types during rolling version upgrades."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class EventType(Enum):
    """Canonical set of known event types the orchestrator handles."""

    # Lifecycle events
    TASK_SUBMITTED = "task.submitted"
    TASK_DISPATCHED = "task.dispatched"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"

    # Workflow events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_STEP_COMPLETED = "workflow.step_completed"
    WORKFLOW_STEP_FAILED = "workflow.step_failed"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_ABORTED = "workflow.aborted"

    # Agent lifecycle
    AGENT_REGISTERED = "agent.registered"
    AGENT_DEREGISTERED = "agent.deregistered"
    AGENT_HEARTBEAT = "agent.heartbeat"
    AGENT_TIMEOUT = "agent.timeout"

    # Scheduler events
    SCHEDULER_TICK = "scheduler.tick"
    QUEUE_DRAINED = "queue.drained"

    @classmethod
    def known_types(cls) -> Set[str]:
        return {e.value for e in cls}


class LifecycleRevision:
    """Tracks the attempt, revision, and lifecycle phase for state transitions."""

    def __init__(
        self,
        attempt: int = 1,
        revision: int = 1,
        lifecycle: str = "active",
        version: str = "1.0.0",
    ):
        self.attempt = attempt
        self.revision = revision
        self.lifecycle = lifecycle
        self.version = version

    def allowed(self, target: "LifecycleRevision") -> bool:
        """Check whether transitioning *to* the target revision is valid.

        Rules:
          - Same version: revision must be strictly increasing.
          - Different version (rolling upgrade): lifecycle must be 'active'
            and attempt must be 1 (no retry of unknown-version events).
        """
        if self.version == target.version:
            # Normal progression — monotonically increasing revision
            return target.revision > self.revision
        else:
            # Rolling version upgrade — only accept if current lifecycle
            # is active and this is a first attempt (not a retry of a
            # stale event).
            return self.lifecycle == "active" and target.attempt == 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt": self.attempt,
            "revision": self.revision,
            "lifecycle": self.lifecycle,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LifecycleRevision":
        return cls(
            attempt=data.get("attempt", 1),
            revision=data.get("revision", 1),
            lifecycle=data.get("lifecycle", "active"),
            version=data.get("version", "1.0.0"),
        )

    def __repr__(self) -> str:
        return (
            f"LifecycleRevision("
            f"attempt={self.attempt}, "
            f"revision={self.revision}, "
            f"lifecycle={self.lifecycle!r}, "
            f"version={self.version!r})"
        )


class EventQuarantine:
    """Guard that rejects or defers unknown event types during rolling upgrades.

    During a rolling version upgrade, the orchestrator may receive events
    in a format or of a type that the current version does not understand.
    This quarantine intercepts such events so they are never committed to
    workflow state.
    """

    def __init__(self, known_types: Optional[Set[str]] = None):
        self._known_types = known_types or EventType.known_types()
        self._quarantined: List[Dict[str, Any]] = []
        self._quarantine_count: int = 0

    def accepts(
        self,
        event_type: str,
        revision: LifecycleRevision,
        current_state: LifecycleRevision,
    ) -> bool:
        """Check whether *event_type* can be dispatched given current state.

        Returns ``True`` (accept) or ``False`` (quarantine).

        A caller should **not** commit state changes if this returns False.
        """
        if event_type in self._known_types:
            return revision.allowed(current_state)
        return False

    def quarantine(self, event: Dict[str, Any], reason: str) -> None:
        """Record a quarantined event for audit/debugging."""
        self._quarantined.append(
            {
                "event": event,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._quarantine_count += 1

    @property
    def quarantined(self) -> List[Dict[str, Any]]:
        return list(self._quarantined)

    @property
    def quarantine_count(self) -> int:
        return self._quarantine_count

    def clear_quarantine(self) -> None:
        self._quarantined.clear()
        self._quarantine_count = 0

    def register_event_type(self, event_type: str) -> None:
        """Dynamically register a new event type (useful for plugin systems)."""
        self._known_types.add(event_type)

    def __repr__(self) -> str:
        return (
            f"EventQuarantine("
            f"known_types={len(self._known_types)}, "
            f"quarantined={self._quarantine_count})"
        )
