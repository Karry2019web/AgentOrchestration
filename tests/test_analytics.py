"""Tests for analytics anonymization validation."""
import pytest
from src.common.analytics import AnalyticsPublisher, MetricGroup, AnonymizationError


class TestAnalyticsPublisher:
    def setup_method(self):
        self.publisher = AnalyticsPublisher(min_group_size=5)

    def test_publishes_large_groups(self):
        groups = [
            MetricGroup(group_key="workspace_a", count=100, metrics={"task_count": 50}),
        ]
        result = self.publisher.validate_and_publish(groups)
        assert result["published"] == 1
        assert len(result["suppressed"]) == 0

    def test_suppresses_small_groups(self):
        groups = [
            MetricGroup(group_key="workspace_b", count=3, metrics={"task_count": 2}),
            MetricGroup(group_key="workspace_c", count=20, metrics={"task_count": 15}),
        ]
        result = self.publisher.validate_and_publish(groups)
        assert result["published"] == 1
        assert "workspace_b" in result["suppressed"]
        assert "workspace_c" not in result["suppressed"]

    def test_rejects_all_below_threshold(self):
        groups = [
            MetricGroup(group_key="small_a", count=2, metrics={"task_count": 1}),
            MetricGroup(group_key="small_b", count=4, metrics={"task_count": 3}),
        ]
        with pytest.raises(AnonymizationError):
            self.publisher.validate_and_publish(groups)

    def test_empty_groups(self):
        result = self.publisher.validate_and_publish([])
        assert result["published"] == 0
        assert result["suppressed"] == []

    def test_boundary_at_minimum(self):
        publisher = AnalyticsPublisher(min_group_size=5)
        groups = [
            MetricGroup(group_key="boundary_test", count=5, metrics={"task_count": 5}),
        ]
        result = publisher.validate_and_publish(groups)
        assert result["published"] == 1

    def test_suppressed_groups_not_exposed(self):
        publisher = AnalyticsPublisher(min_group_size=10)
        groups = [
            MetricGroup(group_key="secret", count=3, metrics={"sensitive": 999}),
        ]
        with pytest.raises(AnonymizationError):
            publisher.validate_and_publish(groups)
        # Suppressed groups recorded without metric values
        suppressed = publisher.get_suppressed_groups()
        assert "secret" in suppressed
