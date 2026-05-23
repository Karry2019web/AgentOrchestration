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
        # Track min and max per histogram
        self._histogram_mins: Dict[str, float] = {}
        self._histogram_maxs: Dict[str, float] = {}

    def increment(self, metric: str, value: int = 1) -> None:
        with self._lock:
            self._counters[metric] += value

    def gauge(self, metric: str, value: float) -> None:
        with self._lock:
            self._gauges[metric] = value

    def observe(self, metric: str, value: float) -> None:
        with self._lock:
            self._histograms[metric].append(value)
            # Track min
            if metric in self._histogram_mins:
                if value < self._histogram_mins[metric]:
                    self._histogram_mins[metric] = value
            else:
                self._histogram_mins[metric] = value
            # Track max
            if metric in self._histogram_maxs:
                if value > self._histogram_maxs[metric]:
                    self._histogram_maxs[metric] = value
            else:
                self._histogram_maxs[metric] = value

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
                "histograms": {
                    k: {
                        "count": len(v),
                        "sum": sum(v),
                        "avg": sum(v) / len(v) if v else 0,
                        "min": self._histogram_mins.get(k, 0),
                        "max": self._histogram_maxs.get(k, 0),
                    }
                    for k, v in self._histograms.items()
                },
            }


metrics = MetricsCollector()
