"""Model Routing Guard — Prevents routing to unsupported model modes."""

import time
import logging
from enum import Enum
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


class ModelMode(Enum):
    CHAT = "chat"
    COMPLETION = "completion"
    EMBEDDING = "embedding"
    IMAGE = "image"
    AUDIO = "audio"
    TOOL_CALL = "tool_call"
    STREAMING = "streaming"


SUPPORTED_MODES: Set[ModelMode] = {
    ModelMode.CHAT,
    ModelMode.COMPLETION,
    ModelMode.EMBEDDING,
    ModelMode.TOOL_CALL,
    ModelMode.STREAMING,
}

# Modes that are not yet supported for routing fallback
UNSUPPORTED_FALLBACK_MODES: Set[ModelMode] = {
    ModelMode.IMAGE,
    ModelMode.AUDIO,
}


class RoutingDecision:
    """Immutable record of a routing guard decision."""

    def __init__(self, mode: ModelMode, allowed: bool, reason: str, timestamp: float):
        self.mode = mode
        self.allowed = allowed
        self.reason = reason
        self.timestamp = timestamp

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "allowed": self.allowed,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class ModelRoutingGuard:
    """State-machine guard that validates and controls model routing fallback.

    Prevents routing to unsupported modes, persists durable state before
    emitting side effects, and ensures retries are bounded and idempotent.
    """

    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries
        self._decisions: Dict[str, list] = {}
        self._routing_state: Dict[str, Dict] = {}

    def check_fallback(
        self,
        route_id: str,
        target_mode: ModelMode,
        fallback_chain: Optional[list] = None,
    ) -> RoutingDecision:
        """Check whether a routing fallback to *target_mode* is allowed."""
        if target_mode in UNSUPPORTED_FALLBACK_MODES:
            decision = RoutingDecision(
                mode=target_mode,
                allowed=False,
                reason=(
                    f"Mode {target_mode.value} is not supported for routing "
                    f"fallback. Supported modes: {[m.value for m in SUPPORTED_MODES]}"
                ),
                timestamp=time.time(),
            )
        elif fallback_chain and any(
            m in UNSUPPORTED_FALLBACK_MODES for m in fallback_chain
        ):
            unsupported = [m.value for m in fallback_chain if m in UNSUPPORTED_FALLBACK_MODES]
            decision = RoutingDecision(
                mode=target_mode,
                allowed=False,
                reason=f"Fallback chain contains unsupported modes: {unsupported}",
                timestamp=time.time(),
            )
        else:
            decision = RoutingDecision(
                mode=target_mode,
                allowed=True,
                reason="Routing fallback allowed — target mode is supported",
                timestamp=time.time(),
            )

        self._persist_decision(route_id, decision)
        return decision

    def record_routing(
        self,
        route_id: str,
        resolved_mode: ModelMode,
        attempt: int = 1,
    ) -> bool:
        """Record a routing attempt with bounded retries.

        Returns True if the attempt is allowed, False if retry limit is exceeded.
        """
        if route_id not in self._routing_state:
            self._routing_state[route_id] = {
                "last_attempt": 0,
                "resolved_mode": None,
                "terminal": False,
                "created_at": time.time(),
            }

        state = self._routing_state[route_id]

        if state["terminal"]:
            logger.info(
                f"Route {route_id} already terminal (mode={state['resolved_mode']})"
            )
            return False

        if attempt > self._max_retries:
            state["terminal"] = True
            logger.warning(
                f"Route {route_id} exceeded max retries ({self._max_retries})"
            )
            return False

        if attempt <= state["last_attempt"]:
            # Idempotent: same or earlier attempt — no-op
            logger.debug(
                f"Route {route_id} attempt {attempt} <= last {state['last_attempt']}, skip"
            )
            return True

        state["last_attempt"] = attempt
        state["resolved_mode"] = resolved_mode.value
        logger.info(
            f"Route {route_id} resolved to {resolved_mode.value} (attempt {attempt})"
        )
        return True

    def mark_terminal(self, route_id: str) -> None:
        """Mark a route as terminal — no further retries allowed."""
        if route_id in self._routing_state:
            self._routing_state[route_id]["terminal"] = True
            logger.info(f"Route {route_id} marked terminal")

    def get_routing_state(self, route_id: str) -> Optional[Dict]:
        """Get durable routing state for a route."""
        return self._routing_state.get(route_id)

    def _persist_decision(self, route_id: str, decision: RoutingDecision) -> None:
        """Persist a routing decision before any side effects are emitted."""
        if route_id not in self._decisions:
            self._decisions[route_id] = []
        self._decisions[route_id].append(decision)
        logger.debug(
            f"Persisted routing decision for {route_id}: "
            f"allowed={decision.allowed}, reason={decision.reason}"
        )

    def get_decisions(self, route_id: str) -> list:
        """Retrieve persisted decisions for a route."""
        return self._decisions.get(route_id, [])

    @property
    def max_retries(self) -> int:
        return self._max_retries
