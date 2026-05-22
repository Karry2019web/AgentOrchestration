"""Analytics warehouse — Anonymization validation before publish.

Enforces minimum aggregation thresholds and verifies anonymization
flags before publishing aggregated task metrics to the analytics
warehouse. Small groups (< configured minimum size) are blocked
to prevent re-identification from sparse aggregates.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class AnonymizationError(Exception):
    """Raised when an analytics publish violates anonymization rules."""
    pass


@dataclass
class MetricGroup:
    """A group of aggregated metric observations."""
    group_key: str
    count: int
    metrics: Dict[str, float] = field(default_factory=dict)


class AnalyticsPublisher:
    """Analytics warehouse publisher with publish-time anonymization validation.

    Enforces:
    - Minimum group size (anonymity threshold) before publishing
    - Blocked groups are reported without exposing their contents
    """

    DEFAULT_MIN_GROUP_SIZE = 5

    def __init__(self, min_group_size: int = DEFAULT_MIN_GROUP_SIZE):
        self.min_group_size = min_group_size
        self._suppressed_groups: List[str] = []

    def validate_and_publish(self, groups: List[MetricGroup]) -> Dict:
        """Validate anonymization thresholds and publish metric groups.

        Args:
            groups: List of aggregated metric groups to publish.

        Returns:
            Dict with 'published' count and 'suppressed' group keys.

        Raises:
            AnonymizationError: If all groups are below the anonymity threshold.
        """
        if not groups:
            return {"published": 0, "suppressed": []}

        publishable = []
        self._suppressed_groups = []

        for group in groups:
            if group.count >= self.min_group_size:
                # Anonymity threshold met — safe to publish
                publishable.append(group)
            else:
                # Below threshold — suppress without exposing contents
                self._suppressed_groups.append(group.group_key)

        if not publishable:
            raise AnonymizationError(
                f"No metric groups meet the minimum anonymity threshold "
                f"of {self.min_group_size}. "
                f"Suppressed groups: {len(self._suppressed_groups)}"
            )

        self._do_publish(publishable)

        return {
            "published": len(publishable),
            "suppressed": list(self._suppressed_groups),
        }

    def get_suppressed_groups(self) -> List[str]:
        """Return list of suppressed group keys without exposing metric values."""
        return list(self._suppressed_groups)

    def _do_publish(self, groups: List[MetricGroup]) -> None:
        """Internal publish — in production this writes to the analytics warehouse.

        This implementation logs the publish event. Subclasses should
        override with the actual warehouse client.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            "Published %d metric groups to analytics warehouse "
            "(min_group_size=%d)",
            len(groups),
            self.min_group_size,
        )
