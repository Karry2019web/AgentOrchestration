"""Tests for metrics collection and analytics publishing with anonymization validation."""

import pytest
from src.common.metrics import MetricsCollector, AnalyticsPublisher, AnalyticsPublishError


class TestMetricsCollector:
    def setup_method(self):
        self.metrics = MetricsCollector()

    def test_increment(self):
        self.metrics.increment("requests.total")
        self.metrics.increment("requests.total")
        snapshot = self.metrics.snapshot()
        assert snapshot["counters"]["requests.total"] == 2

    def test_gauge(self):
        self.metrics.gauge("memory.usage", 85.5)
        snapshot = self.metrics.snapshot()
        assert snapshot["gauges"]["memory.usage"] == 85.5

    def test_observe(self):
        self.metrics.observe("response.time", 0.5)
        self.metrics.observe("response.time", 1.5)
        snapshot = self.metrics.snapshot()
        assert snapshot["histograms"]["response.time"]["count"] == 2
        assert snapshot["histograms"]["response.time"]["avg"] == 1.0

    def test_timer(self):
        self.metrics.start_timer("operation")
        import time
        time.sleep(0.01)
        duration = self.metrics.stop_timer("operation")
        assert duration > 0.005


class TestAnalyticsPublisher:
    def setup_method(self):
        self.publisher = AnalyticsPublisher(min_group_size=5)

    def test_publish_above_threshold(self):
        """Groups at or above the minimum size are published successfully."""
        group = {
            "group_id": "workspace_alpha",
            "group_size": 10,
            "metrics": {"total_tasks": 42, "avg_duration": 3.5},
        }
        result = self.publisher.publish(group)
        assert result["group_id"] == "workspace_alpha"
        assert result["group_size"] == 10
        assert result["metrics"]["total_tasks"] == 42

    def test_publish_at_threshold(self):
        """Groups exactly at minimum size are published."""
        group = {
            "group_id": "workspace_beta",
            "group_size": 5,
            "metrics": {"total_tasks": 15},
        }
        result = self.publisher.publish(group)
        assert result["group_size"] == 5

    def test_publish_below_threshold_raises(self):
        """Groups below the minimum size are rejected."""
        group = {
            "group_id": "workspace_gamma",
            "group_size": 2,
            "metrics": {"total_tasks": 7},
        }
        with pytest.raises(AnalyticsPublishError) as exc_info:
            self.publisher.publish(group)
        assert "workspace_gamma" in str(exc_info.value)
        assert "2" in str(exc_info.value)
        assert "5" in str(exc_info.value)

    def test_publish_empty_group(self):
        """Groups with zero size are always rejected."""
        group = {
            "group_id": "workspace_empty",
            "group_size": 0,
            "metrics": {},
        }
        with pytest.raises(AnalyticsPublishError):
            self.publisher.publish(group)

    def test_publish_single_entity_group(self):
        """A single-entity group is rejected (re-identification risk)."""
        group = {
            "group_id": "workspace_solo",
            "group_size": 1,
            "metrics": {"total_tasks": 3},
        }
        with pytest.raises(AnalyticsPublishError):
            self.publisher.publish(group)

    def test_publish_batch_all_valid(self):
        """Batch publish with all groups above threshold."""
        groups = [
            {"group_id": "a", "group_size": 10, "metrics": {"x": 1}},
            {"group_id": "b", "group_size": 20, "metrics": {"x": 2}},
        ]
        result = self.publisher.publish_batch(groups)
        assert result["published_count"] == 2
        assert result["suppressed_count"] == 0
        assert len(result["suppressed"]) == 0

    def test_publish_batch_mixed(self):
        """Batch publish with some groups below threshold."""
        groups = [
            {"group_id": "large", "group_size": 100, "metrics": {"x": 10}},
            {"group_id": "small", "group_size": 2, "metrics": {"x": 1}},
            {"group_id": "medium", "group_size": 7, "metrics": {"x": 5}},
        ]
        result = self.publisher.publish_batch(groups)
        assert result["published_count"] == 2
        assert result["suppressed_count"] == 1
        assert "small" in result["suppressed"]
        assert "large" not in result["suppressed"]

    def test_publish_batch_all_below(self):
        """Batch publish with all groups below threshold."""
        groups = [
            {"group_id": "tiny", "group_size": 1, "metrics": {"x": 1}},
            {"group_id": "small", "group_size": 3, "metrics": {"x": 2}},
        ]
        result = self.publisher.publish_batch(groups)
        assert result["published_count"] == 0
        assert result["suppressed_count"] == 2

    def test_custom_min_group_size(self):
        """Publisher can be configured with a custom minimum group size."""
        publisher = AnalyticsPublisher(min_group_size=3)
        assert publisher.min_group_size == 3

        # Below custom threshold
        group = {"group_id": "g", "group_size": 2, "metrics": {}}
        with pytest.raises(AnalyticsPublishError):
            publisher.publish(group)

        # At custom threshold
        group = {"group_id": "g", "group_size": 3, "metrics": {}}
        result = publisher.publish(group)
        assert result["group_size"] == 3

    def test_suppressed_groups_not_exposed(self):
        """Suppressed groups are reported by ID only, without exposing their metrics."""
        groups = [
            {"group_id": "exposed", "group_size": 10, "metrics": {"secret_data": "should_appear"}},
            {"group_id": "hidden", "group_size": 1, "metrics": {"secret_data": "should_not_leak"}},
        ]
        result = self.publisher.publish_batch(groups)
        assert "hidden" in result["suppressed"]
        # Suppressed list only contains IDs, not the full group data
        assert all(isinstance(s, str) for s in result["suppressed"])
        # Published groups retain their metrics
        published_ids = [p["group_id"] for p in result["published"]]
        assert "exposed" in published_ids
        assert "hidden" not in published_ids

