"""Metrics collection and reporting."""

import time
from collections import defaultdict
from typing import Dict, List
from threading import Lock


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
        # Copy minimal data under lock — formatting outside the critical section
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms = {k: list(v) for k, v in self._histograms.items()}

        # Compute aggregates outside the lock so threaded exporters
        # don't block metric recording during processing.
        histograms_formatted = {}
        for k, v in histograms.items():
            histograms_formatted[k] = {
                "count": len(v),
                "sum": sum(v),
                "avg": sum(v) / len(v) if v else 0,
            }

        return {
            "counters": counters,
            "gauges": gauges,
            "histograms": histograms_formatted,
        }


metrics = MetricsCollector()
