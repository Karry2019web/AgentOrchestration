"""Canary Analyzer — Queue backlog and worker throughput metrics for canary decisions."""

import time
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default canary thresholds
DEFAULT_BACKLOG_THRESHOLD = 50
DEFAULT_LATENCY_THRESHOLD = 30.0  # seconds
DEFAULT_LEASE_RENEWAL_FAILURE_RATE = 0.1  # 10% failure rate triggers rollback


class CanaryMetrics:
    """Aggregated metrics snapshot for canary analysis."""

    def __init__(self):
        self.queue_depth: Dict[str, int] = {}
        self.processing_latency: Dict[str, float] = {}
        self.in_flight_count: int = 0
        self.lease_renewal_attempts: int = 0
        self.lease_renewal_failures: int = 0
        self.worker_count: int = 0
        self.timestamp: float = time.time()

    def to_dict(self) -> Dict:
        return {
            "queue_depth": self.queue_depth,
            "processing_latency": self.processing_latency,
            "in_flight_count": self.in_flight_count,
            "lease_renewal_attempts": self.lease_renewal_attempts,
            "lease_renewal_failure_rate": (
                self.lease_renewal_failures / self.lease_renewal_attempts
                if self.lease_renewal_attempts > 0 else 0.0
            ),
            "worker_count": self.worker_count,
            "timestamp": self.timestamp,
        }


class CanaryDecision:
    """Result of a canary analysis."""

    def __init__(self, passed: bool, metrics: CanaryMetrics, reasons: List[str]):
        self.passed = passed
        self.metrics = metrics
        self.reasons = reasons

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "metrics": self.metrics.to_dict(),
            "reasons": self.reasons,
        }


class CanaryAnalyzer:
    """Evaluates queue and worker metrics for canary promotion decisions.

    The analyzer checks:
    - Queue backlog depth per queue
    - Processing latency (time tasks sit in queue)
    - Worker lease renewal failure rates
    - In-flight task saturation
    """

    def __init__(
        self,
        backlog_threshold: int = DEFAULT_BACKLOG_THRESHOLD,
        latency_threshold: float = DEFAULT_LATENCY_THRESHOLD,
        lease_failure_rate_threshold: float = DEFAULT_LEASE_RENEWAL_FAILURE_RATE,
    ):
        self.backlog_threshold = backlog_threshold
        self.latency_threshold = latency_threshold
        self.lease_failure_rate_threshold = lease_failure_rate_threshold
        self._lease_renewal_attempts: int = 0
        self._lease_renewal_failures: int = 0

    def record_lease_renewal(self, success: bool) -> None:
        self._lease_renewal_attempts += 1
        if not success:
            self._lease_renewal_failures += 1

    def analyze(
        self,
        queue_depths: Dict[str, int],
        processing_latencies: Dict[str, float],
        in_flight_count: int,
        worker_count: int,
    ) -> CanaryDecision:
        """Run canary analysis against current metrics.

        Args:
            queue_depths: Per-queue task backlog counts.
            processing_latencies: Per-queue average processing latency in seconds.
            in_flight_count: Number of tasks currently being processed.
            worker_count: Number of active workers.

        Returns:
            CanaryDecision with pass/fail and detailed reasons.
        """
        metrics = CanaryMetrics()
        metrics.queue_depth = queue_depths
        metrics.processing_latency = processing_latencies
        metrics.in_flight_count = in_flight_count
        metrics.lease_renewal_attempts = self._lease_renewal_attempts
        metrics.lease_renewal_failures = self._lease_renewal_failures
        metrics.worker_count = worker_count

        reasons: List[str] = []
        passed = True

        # Check queue backlog depth
        total_backlog = sum(queue_depths.values())
        if total_backlog > self.backlog_threshold:
            reasons.append(
                f"Queue backlog {total_backlog} exceeds threshold {self.backlog_threshold}"
            )
            passed = False
        else:
            reasons.append(f"Queue backlog {total_backlog} within threshold")

        # Check per-queue processing latency
        for queue_name, latency in processing_latencies.items():
            if latency > self.latency_threshold:
                reasons.append(
                    f"Queue '{queue_name}' latency {latency:.1f}s exceeds "
                    f"threshold {self.latency_threshold}s"
                )
                passed = False
            else:
                reasons.append(f"Queue '{queue_name}' latency {latency:.1f}s within threshold")

        # Check lease renewal failure rate
        if self._lease_renewal_attempts > 0:
            failure_rate = self._lease_renewal_failures / self._lease_renewal_attempts
            if failure_rate > self.lease_failure_rate_threshold:
                reasons.append(
                    f"Lease renewal failure rate {failure_rate:.1%} exceeds "
                    f"threshold {self.lease_failure_rate_threshold:.1%}"
                )
                passed = False
            else:
                reasons.append(
                    f"Lease renewal failure rate {failure_rate:.1%} within threshold"
                )

        # Check worker saturation
        if worker_count > 0 and in_flight_count >= worker_count:
            reasons.append(
                f"In-flight tasks ({in_flight_count}) at worker capacity ({worker_count})"
            )
            passed = False
        elif worker_count > 0:
            reasons.append(
                f"In-flight tasks ({in_flight_count}) below worker capacity ({worker_count})"
            )

        logger.info(
            "Canary analysis: passed=%s, reasons=%s", passed, reasons
        )
        return CanaryDecision(passed=passed, metrics=metrics, reasons=reasons)

    def reset_metrics(self) -> None:
        """Reset accumulated lease renewal counters."""
        self._lease_renewal_attempts = 0
        self._lease_renewal_failures = 0
        logger.debug("Canary metrics reset")
