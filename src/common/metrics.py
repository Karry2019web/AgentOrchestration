"""Metrics collection and analytics publishing with anonymization validation."""

import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Any
from threading import Lock

logger = logging.getLogger(__name__)


class MetricsCollector:
    def __init__(self):
        self._lock = Lock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._timers: Dict[str, float] = {}

    def increment(self, metric: str, value: int = 1) -> None:
        with self._lock:
            self._counters[metric] += value

    def gauge(self, metric: str, value: float) -> None:
        with self._lock:
            self._gauges[metric] = value

    def observe(self, metric: str, value: float) -> None:
        with self._lock:
            self._histograms[metric].append(value)

    def start_timer(self, metric: str) -> None:
        with self._lock:
            self._timers[metric] = time.time()

    def stop_timer(self, metric: str) -> float:
        with self._lock:
            if metric in self._timers:
                duration = time.time() - self._timers.pop(metric)
                self.observe(metric, duration)
                return duration
        return 0.0

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: {"count": len(v), "sum": sum(v), "avg": sum(v) / len(v) if v else 0}
                               for k, v in self._histograms.items()},
            }


metrics = MetricsCollector()


class AnalyticsPublishError(Exception):
    """Raised when analytics metric publication fails validation."""
    pass


class AnalyticsPublisher:
    """Publishes aggregated metrics to an analytics warehouse with anonymization validation.

    Enforces minimum group-size thresholds before publishing to prevent
    re-identification of individual workspaces or tasks through aggregate data.
    """

    def __init__(self, min_group_size: int = 5):
        self._min_group_size = min_group_size

    @property
    def min_group_size(self) -> int:
        return self._min_group_size

    def publish(self, metric_group: Dict[str, Any]) -> Dict[str, Any]:
        """Publish a metric group after validating anonymization thresholds.

        Args:
            metric_group: A dict with keys:
                - "group_id": str — identifier for the metric group
                - "group_size": int — number of entities aggregated in this group
                - "metrics": dict — the aggregated metric values

        Returns:
            The validated metric group as published.

        Raises:
            AnalyticsPublishError: If the group size is below the minimum threshold.
        """
        group_size = metric_group.get("group_size", 0)
        group_id = metric_group.get("group_id", "unknown")

        if group_size < self._min_group_size:
            logger.warning(
                "Analytics publish blocked for group %s: size %d below minimum %d",
                group_id, group_size, self._min_group_size,
            )
            raise AnalyticsPublishError(
                f"Group '{group_id}' size ({group_size}) below anonymity threshold ({self._min_group_size})"
            )

        logger.info(
            "Analytics published for group %s: size %d meets threshold %d",
            group_id, group_size, self._min_group_size,
        )
        return dict(metric_group)

    def publish_batch(self, metric_groups: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Publish multiple metric groups, suppressing groups below threshold.

        Args:
            metric_groups: List of metric group dicts.

        Returns:
            Dict with keys:
                - "published": list of successfully published groups
                - "suppressed": list of group IDs that were below the anonymity threshold
                - "suppressed_count": int
                - "published_count": int
        """
        published = []
        suppressed = []

        for group in metric_groups:
            try:
                result = self.publish(group)
                published.append(result)
            except AnalyticsPublishError:
                suppressed.append(group.get("group_id", "unknown"))

        return {
            "published": published,
            "suppressed": suppressed,
            "suppressed_count": len(suppressed),
            "published_count": len(published),
        }

