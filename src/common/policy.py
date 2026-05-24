"""Policy Engine -- Authorization and policy evaluation runtime.

This module implements a policy engine that evaluates whether an operation
should be allowed or denied. When the policy engine is unavailable, all
operations fail closed (denied by default) to maintain security posture.
"""

import logging
import time
from typing import Any, Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class PolicyDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ERROR = "error"


class PolicyEngine:
    """Evaluates policy constraints for orchestration operations.

    Fail-closed semantics: if the engine cannot reach its policy store,
    all operations are denied rather than allowed through.
    """

    def __init__(self, endpoint: Optional[str] = None, timeout: float = 5.0):
        self._endpoint = endpoint
        self._timeout = timeout
        self._healthy = True
        self._last_health_check = 0.0
        self._health_check_interval = 30.0

    def is_available(self) -> bool:
        """Check whether the policy engine is reachable and healthy.

        Uses a cached health check with a configurable interval to
        avoid hammering the backend on every evaluation.
        """
        now = time.time()
        if now - self._last_health_check < self._health_check_interval:
            return self._healthy

        self._last_health_check = now
        if not self._endpoint:
            self._healthy = True
            return True

        try:
            import httpx
            resp = httpx.get(
                f"{self._endpoint}/health",
                timeout=self._timeout,
            )
            self._healthy = resp.is_success
        except Exception as e:
            logger.warning(f"Policy engine health check failed: {e}")
            self._healthy = False

        return self._healthy

    def evaluate(
        self,
        action: str,
        resource: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecision:
        """Evaluate whether *action* on *resource* is allowed.

        Fail-closed: returns DENY when the engine is unavailable.
        """
        if not self.is_available():
            logger.error(
                "Policy engine unavailable -- failing closed for "
                "action=%s resource=%s",
                action,
                resource,
            )
            return PolicyDecision.DENY

        if not self._endpoint:
            return PolicyDecision.ALLOW

        try:
            import httpx
            payload = {
                "action": action,
                "resource": resource,
                "context": context or {},
            }
            resp = httpx.post(
                f"{self._endpoint}/evaluate",
                json=payload,
                timeout=self._timeout,
            )
            if resp.is_success:
                result = resp.json()
                return PolicyDecision(result.get("decision", "deny"))
            logger.warning(
                "Policy engine returned %d -- denying action=%s",
                resp.status_code,
                action,
            )
            return PolicyDecision.DENY
        except Exception as e:
            logger.error(
                "Policy engine evaluation error for action=%s: %s -- failing closed",
                action,
                e,
            )
            self._healthy = False
            return PolicyDecision.DENY

# 2026-05-24T05:58:00 update
