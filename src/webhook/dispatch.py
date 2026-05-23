"""Per-endpoint rate limiter for webhook fanout dispatch.

Enforces rate limits on a per-endpoint basis during fanout to prevent
unbounded work from consuming CPU, memory, queue slots, or network time.
"""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class FanoutPolicy(Enum):
    """Controls how a fanout dispatch behaves when rate limits are exceeded."""
    BLOCK = "block"
    DROP = "drop"
    QUEUE_BACKPRESSURE = "queue_backpressure"
    BYPASS = "bypass"


@dataclass
class RateLimitWindow:
    """Tracks request timestamps within a sliding window."""
    window_seconds: float
    max_requests: int
    timestamps: List[float] = field(default_factory=list)

    def is_allowed(self) -> Tuple[bool, int]:
        now = time.time()
        cutoff = now - self.window_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        if len(self.timestamps) < self.max_requests:
            self.timestamps.append(now)
            return True, 0
        oldest = self.timestamps[0]
        retry_after = max(1, int(oldest + self.window_seconds - now))
        return False, retry_after

    def reset(self) -> None:
        self.timestamps.clear()


@dataclass
class EndpointRateLimit:
    endpoint_id: str
    window_seconds: float = 60.0
    max_requests: int = 100
    policy: FanoutPolicy = FanoutPolicy.BLOCK
    enabled: bool = True

    def to_dict(self) -> Dict:
        return {
            "endpoint_id": self.endpoint_id,
            "window_seconds": self.window_seconds,
            "max_requests": self.max_requests,
            "policy": self.policy.value,
            "enabled": self.enabled,
        }


class EndpointRateLimiter:
    def __init__(self):
        self._lock = Lock()
        self._limits: Dict[str, EndpointRateLimit] = {}
        self._windows: Dict[str, RateLimitWindow] = {}
        self._default_limit = EndpointRateLimit(
            endpoint_id="__default__",
            window_seconds=60.0,
            max_requests=100,
            policy=FanoutPolicy.BLOCK,
        )

    def configure(self, endpoint_id: str, max_requests: int,
                  window_seconds: float = 60.0,
                  policy: FanoutPolicy = FanoutPolicy.BLOCK) -> None:
        with self._lock:
            self._limits[endpoint_id] = EndpointRateLimit(
                endpoint_id=endpoint_id,
                window_seconds=window_seconds,
                max_requests=max_requests,
                policy=policy,
            )
            if endpoint_id not in self._windows:
                self._windows[endpoint_id] = RateLimitWindow(
                    window_seconds=window_seconds,
                    max_requests=max_requests,
                )

    def remove(self, endpoint_id: str) -> bool:
        with self._lock:
            self._limits.pop(endpoint_id, None)
            self._windows.pop(endpoint_id, None)
            return True

    def get_limit(self, endpoint_id: str) -> EndpointRateLimit:
        with self._lock:
            return self._limits.get(endpoint_id, self._default_limit)

    def check(self, endpoint_id: str) -> Tuple[bool, int, str]:
        with self._lock:
            limit = self._limits.get(endpoint_id, self._default_limit)
            if not limit.enabled:
                return True, 0, "rate_limit_disabled"
            if endpoint_id not in self._windows:
                self._windows[endpoint_id] = RateLimitWindow(
                    window_seconds=limit.window_seconds,
                    max_requests=limit.max_requests,
                )
            window = self._windows[endpoint_id]
            allowed, retry_after = window.is_allowed()
            if allowed:
                return True, 0, "allowed"
            if limit.policy == FanoutPolicy.BYPASS:
                return True, 0, "bypass_policy"
            elif limit.policy == FanoutPolicy.DROP:
                return False, retry_after, "rate_limited_dropped"
            elif limit.policy == FanoutPolicy.QUEUE_BACKPRESSURE:
                return False, retry_after, "rate_limited_backpressure"
            else:
                return False, retry_after, "rate_limited_blocked"

    def reset_all(self) -> None:
        with self._lock:
            for window in self._windows.values():
                window.reset()

    def stats(self, endpoint_id: str) -> Dict:
        with self._lock:
            limit = self._limits.get(endpoint_id, self._default_limit)
            window = self._windows.get(endpoint_id)
            current_count = len(window.timestamps) if window else 0
            return {
                "endpoint_id": endpoint_id,
                "limit": limit.to_dict(),
                "current_count": current_count,
                "remaining": max(0, limit.max_requests - current_count),
                "windows_active": len(self._windows),
            }


class DispatchController:
    def __init__(self, rate_limiter: Optional[EndpointRateLimiter] = None):
        self.rate_limiter = rate_limiter or EndpointRateLimiter()
        self._dispatch_count: Dict[str, int] = defaultdict(int)
        self._rejection_count: Dict[str, int] = defaultdict(int)

    def fanout(self, event_id: str, endpoint_ids: List[str],
               workspace_id: str = "default") -> List[Dict]:
        results = []
        for endpoint_id in endpoint_ids:
            allowed, retry_after, reason = self.rate_limiter.check(endpoint_id)
            if allowed:
                self._dispatch_count[endpoint_id] += 1
                results.append({
                    "event_id": event_id,
                    "endpoint_id": endpoint_id,
                    "workspace_id": workspace_id,
                    "status": "dispatched",
                    "reason": reason,
                })
            else:
                self._rejection_count[endpoint_id] += 1
                results.append({
                    "event_id": event_id,
                    "endpoint_id": endpoint_id,
                    "workspace_id": workspace_id,
                    "status": "rejected",
                    "reason": reason,
                    "retry_after_seconds": retry_after,
                })
        return results

    def dispatch(self, event_id: str, endpoint_id: str,
                 workspace_id: str = "default") -> Dict:
        allowed, retry_after, reason = self.rate_limiter.check(endpoint_id)
        if allowed:
            self._dispatch_count[endpoint_id] += 1
            return {
                "event_id": event_id,
                "endpoint_id": endpoint_id,
                "workspace_id": workspace_id,
                "status": "dispatched",
                "reason": reason,
            }
        self._rejection_count[endpoint_id] += 1
        return {
            "event_id": event_id,
            "endpoint_id": endpoint_id,
            "workspace_id": workspace_id,
            "status": "rejected",
            "reason": reason,
            "retry_after_seconds": retry_after,
        }

    def retry(self, event_id: str, endpoint_id: str,
              workspace_id: str = "default", attempt: int = 1) -> Dict:
        result = self.dispatch(event_id, endpoint_id, workspace_id)
        result["attempt"] = attempt
        result["idempotent"] = True
        return result

    def get_stats(self, endpoint_id: str) -> Dict:
        return {
            "endpoint_id": endpoint_id,
            "total_dispatched": self._dispatch_count.get(endpoint_id, 0),
            "total_rejected": self._rejection_count.get(endpoint_id, 0),
            "rate_limit": self.rate_limiter.stats(endpoint_id),
        }

    def reset_stats(self) -> None:
        self._dispatch_count.clear()
        self._rejection_count.clear()
        self.rate_limiter.reset_all()

# 2026-05-23T06:30:00 update
