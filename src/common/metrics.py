"""Metrics collection and reporting."""

import time
from collections import defaultdict
from typing import Dict, List, Any
from threading import Lock


# Schema version and field definitions for analytics exports
SCHEMA_VERSION = "1.0.0"


FIELD_DICTIONARY = {
    "schema_version": "Semantic version of the export schema. Consumers MUST reject versions they cannot parse.",
    "generated_at": "ISO-8601 timestamp when this export was generated.",
    "field_dictionary": "Mapping of all field names to their semantic descriptions.",
    "counters": "Monotonically increasing integer counters keyed by metric name.",
    "gauges": "Point-in-time floating-point measurements keyed by gauge name.",
    "histograms": "Distribution data keyed by metric name. Each entry has count, sum, and avg.",
}


def apply_export_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap raw data with schema version, generation timestamp, and field definitions.

    Consumers SHOULD verify schema_version before parsing. Versions outside
    the supported range must be rejected with an UnsupportedSchemaVersion error.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "field_dictionary": dict(FIELD_DICTIONARY),
        "data": data,
    }


def validate_schema_version(export: Dict[str, Any], supported_versions: tuple = ("1.0.0",)) -> bool:
    """Validate that an export's schema version is in the supported range.

    Returns True if the schema version is supported.
    Raises UnsupportedSchemaVersion if the version is missing or unsupported.
    """
    version = export.get("schema_version")
    if not version:
        raise UnsupportedSchemaVersion("Missing schema_version in export payload")
    if version not in supported_versions:
        raise UnsupportedSchemaVersion(
            f"Unsupported schema version '{version}'. Supported: {supported_versions}"
        )
    return True


class UnsupportedSchemaVersion(Exception):
    """Raised when an export has an unsupported or missing schema version."""
    pass


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
            raw = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: {"count": len(v), "sum": sum(v), "avg": sum(v) / len(v) if v else 0}
                               for k, v in self._histograms.items()},
            }
        return apply_export_metadata(raw)


metrics = MetricsCollector()
