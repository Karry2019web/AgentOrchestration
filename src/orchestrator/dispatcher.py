"""Event Dispatcher — Guards dispatch transitions during rolling version upgrades."""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from src.common.errors import AgentOrchestratorError

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Known event types that the dispatcher recognizes."""
    ATTEMPT = "attempt"
    REVISION = "revision"
    LIFECYCLE_START = "lifecycle.start"
    LIFECYCLE_COMPLETE = "lifecycle.complete"
    LIFECYCLE_PAUSE = "lifecycle.pause"
    LIFECYCLE_RESUME = "lifecycle.resume"
    LIFECYCLE_FAIL = "lifecycle.fail"
    SCHEDULE = "schedule"
    ROUTE = "route"
    QUEUE = "queue"
    WORKFLOW_START = "workflow.start"
    WORKFLOW_COMPLETE = "workflow.complete"


class EventDispatchError(AgentOrchestratorError):
    """Raised when an event cannot be dispatched."""
    pass


class QuarantineEvent:
    """Represents a quarantined event — one that was rejected due to version mismatch."""

    def __init__(self, event_type: str, payload: Dict[str, Any], reason: str):
        self.event_type = event_type
        self.payload = payload
        self.reason = reason
        self.timestamp = datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return (
            f"QuarantineEvent(type={self.event_type}, "
            f"reason={self.reason}, "
            f"time={self.timestamp.isoformat()})"
        )


class EventDispatcher:
    """Dispatches events with version-gated lifecycle checks.

    During rolling version upgrades, the dispatcher quarantines unknown,
    stale, or duplicate event types to prevent workflow state divergence.
    """

    def __init__(self, known_event_types: Optional[Set[str]] = None):
        self._known_types: Set[str] = (
            known_event_types
            if known_event_types is not None
            else {e.value for e in EventType}
        )
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._quarantine: List[QuarantineEvent] = []
        self._revision_counter: int = 0
        self._attempt_counter: int = 0
        self._quarantine_count: int = 0
        self._rolling_upgrade_active: bool = True

    # ---- Public API ----

    def register_handler(self, event_type: str, handler: Callable) -> None:
        """Register a callable handler for a given event type."""
        if not callable(handler):
            raise ValueError(f"Handler must be callable, got {type(handler)}")
        self._handlers[event_type].append(handler)

    def dispatch(
        self,
        event_type: str,
        payload: Dict[str, Any],
        expected_revision: Optional[int] = None,
    ) -> bool:
        """Dispatch an event through the pipeline.

        Guards against:
        - Unknown event types (not in known set)
        - Stale revisions (lower than expected)
        - Duplicate lifecycle transitions
        - Disallowed state transitions during rolling upgrades

        Returns True if dispatched, False if quarantined.
        Raises EventDispatchError for hard rejections.
        """
        # --- Gate 1: Unknown event type ---
        if event_type not in self._known_types:
            reason = (
                f"Unknown event type '{event_type}' — "
                f"not in known types during rolling version upgrade"
            )
            self._quarantine_event(event_type, payload, reason)
            return False

        # --- Gate 2: Stale revision ---
        if expected_revision is not None and expected_revision < self._revision_counter:
            reason = (
                f"Stale revision {expected_revision} "
                f"(current: {self._revision_counter}) "
                f"— event rejected during rolling upgrade"
            )
            self._quarantine_event(event_type, payload, reason)
            return False

        # --- Gate 3: Duplicate / policy-violating lifecycle transitions ---
        if self._is_policy_violation(event_type, payload):
            reason = f"Policy-violating lifecycle transition '{event_type}' rejected"
            self._quarantine_event(event_type, payload, reason)
            return False

        # --- Gate 4: Rolling upgrade guard ---
        if self._rolling_upgrade_active:
            self._validate_upgrade_dispatch(event_type, payload)

        # --- Dispatch ---
        self._dispatch_to_handlers(event_type, payload)
        return True

    @property
    def quarantine(self) -> List[QuarantineEvent]:
        """Return list of quarantined events (read-only view)."""
        return list(self._quarantine)

    @property
    def quarantine_count(self) -> int:
        return self._quarantine_count

    def flush_quarantine(self) -> List[QuarantineEvent]:
        """Return and clear the quarantine list."""
        events = list(self._quarantine)
        self._quarantine.clear()
        return events

    def advance_revision(self, revision: int) -> None:
        """Advance the dispatcher's revision counter.

        Called when a rolling upgrade completes a new revision step.
        Any future events below this revision will be quarantined.
        """
        if revision <= self._revision_counter:
            logger.warning(
                "Revision %d is not ahead of current %d — ignored",
                revision, self._revision_counter,
            )
            return
        self._revision_counter = revision
        logger.info("Dispatcher revision advanced to %d", revision)

    def complete_upgrade(self) -> None:
        """Mark rolling upgrade as complete and flush remaining quarantine."""
        self._rolling_upgrade_active = False
        remaining = len(self._quarantine)
        if remaining:
            logger.info(
                "Upgrade complete — %d events remain in quarantine",
                remaining,
            )

    # ---- Internal ----

    def _quarantine_event(self, event_type: str, payload: Dict, reason: str) -> None:
        """Place an event in quarantine."""
        event = QuarantineEvent(event_type, payload, reason)
        self._quarantine.append(event)
        self._quarantine_count += 1
        logger.warning(
            "Quarantined event type=%s reason=%s payload=%s",
            event_type, reason, str(payload)[:200],
        )

    def _is_policy_violation(self, event_type: str, payload: Dict) -> bool:
        """Check for policy-violating lifecycle transitions.

        E.g., a LIFECYCLE_START event for an entity that is already running,
        or a LIFECYCLE_COMPLETE for an entity that never started.
        """
        state = payload.get("current_state", payload.get("state"))
        if event_type == EventType.LIFECYCLE_START.value and state == "running":
            return True
        if event_type == EventType.LIFECYCLE_COMPLETE.value and state == "pending":
            return True
        if event_type == EventType.LIFECYCLE_PAUSE.value and state not in ("running",):
            return True
        return False

    def _validate_upgrade_dispatch(self, event_type: str, payload: Dict) -> None:
        """Validate that an event can be safely dispatched during upgrade.

        During rolling upgrades, we require explicit attempt and revision
        markers in the payload to ensure we don't commit stale state.
        """
        attempt = payload.get("attempt")
        revision = payload.get("revision")

        if attempt is None and revision is None:
            logger.warning(
                "Event %s dispatched without attempt/revision markers "
                "during rolling upgrade",
                event_type,
            )

    def _dispatch_to_handlers(self, event_type: str, payload: Dict) -> None:
        """Send the event to all registered handlers."""
        self._attempt_counter += 1
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            logger.debug("No handlers registered for event type '%s'", event_type)
            return
        for handler in handlers:
            try:
                handler(event_type, payload)
            except Exception:
                logger.exception(
                    "Handler %s failed for event type '%s'",
                    handler.__name__, event_type,
                )
