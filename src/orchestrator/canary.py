"""Canary Analysis — Worker rollout health assessment with queue backlog metrics."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.orchestrator.scheduler import SchedulerMetrics

logger = logging.getLogger(__name__)


@dataclass
class CanaryThresholds:
    """Configurable thresholds for canary promotion decisions."""

    max_backlog_depth: int = 50
    """Maximum acceptable queue backlog depth before triggering rollback."""

    max_processing_latency_p99: float = 30.0
    """Maximum acceptable P99 processing latency in seconds."""

    max_lease_failure_ratio: float = 0.1
    """Maximum ratio of lease failures to total leases before rollback."""

    min_health_score: float = 0.7
    """Minimum composite health score (0-1) for promotion."""


@dataclass
class CanaryDecision:
    """Result of a canary analysis."""

    can_promote: bool
    """Whether the canary is safe to promote."""

    reason: str
    """Human-readable explanation of the decision."""

    backlog_depth: int
    """Current queue backlog depth."""

    p99_processing_latency: float
    """P99 processing latency observed."""

    lease_renewal_count: int
    lease_failure_count: int
    lease_failure_ratio: float

    health_score: float


class CanaryAnalyzer:
    """Analyzes scheduler metrics to decide whether a canary can be promoted.

    Evaluates queue backlog depth, processing latency, and lease renewal
    health against configurable thresholds. Produces a CanaryDecision with
    a promotion verdict and supporting diagnostic data.
    """

    def __init__(self, thresholds: Optional[CanaryThresholds] = None):
        self._thresholds = thresholds or CanaryThresholds()

    @property
    def thresholds(self) -> CanaryThresholds:
        return self._thresholds

    def analyze(self, metrics: SchedulerMetrics, backlog_depth: int = 0) -> CanaryDecision:
        """Run canary analysis against a set of scheduler metrics.

        Args:
            metrics: SchedulerMetrics from the worker being evaluated.
            backlog_depth: Current queue backlog depth (may differ from peak).

        Returns:
            CanaryDecision with promotion verdict and diagnostic data.
        """
        p99_latency = metrics.p99_processing_time
        lease_renewals = metrics.lease_renewal_count
        lease_failures = metrics.lease_failure_count
        total_leases = lease_renewals + lease_failures
        lease_failure_ratio = lease_failures / max(total_leases, 1)
        health_score = metrics.health_score
        effective_backlog = max(backlog_depth, metrics.backlog_peak)

        failures: list[str] = []

        # Check backlog depth
        if effective_backlog > self._thresholds.max_backlog_depth:
            failures.append(
                f"Backlog depth {effective_backlog} exceeds threshold "
                f"{self._thresholds.max_backlog_depth}"
            )

        # Check P99 processing latency
        if p99_latency > self._thresholds.max_processing_latency_p99:
            failures.append(
                f"P99 processing latency {p99_latency:.1f}s exceeds threshold "
                f"{self._thresholds.max_processing_latency_p99}s"
            )

        # Check lease failure ratio
        if lease_failure_ratio > self._thresholds.max_lease_failure_ratio:
            failures.append(
                f"Lease failure ratio {lease_failure_ratio:.3f} exceeds threshold "
                f"{self._thresholds.max_lease_failure_ratio}"
            )

        # Check composite health score
        if health_score < self._thresholds.min_health_score:
            failures.append(
                f"Health score {health_score:.2f} below minimum "
                f"{self._thresholds.min_health_score}"
            )

        can_promote = len(failures) == 0
        reason = "All checks passed" if can_promote else "; ".join(failures)

        logger.info(
            "Canary decision: %s (%s) "
            "backlog=%d latency=%.1fs lease_fail_ratio=%.3f health=%.2f",
            "PROMOTE" if can_promote else "ROLLBACK",
            reason,
            effective_backlog,
            p99_latency,
            lease_failure_ratio,
            health_score,
        )

        return CanaryDecision(
            can_promote=can_promote,
            reason=reason,
            backlog_depth=effective_backlog,
            p99_processing_latency=p99_latency,
            lease_renewal_count=lease_renewals,
            lease_failure_count=lease_failures,
            lease_failure_ratio=lease_failure_ratio,
            health_score=health_score,
        )


# 2026-05-20T10:00:00Z canary module initial
