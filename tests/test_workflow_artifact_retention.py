"""Tests for artifact retention policy validation."""

import pytest
from src.orchestrator.workflow import (
    ArtifactRetentionPolicy,
    ArtifactRetentionValidator,
    Workflow,
    WorkflowManager,
)


class TestArtifactRetentionPolicy:
    def test_valid_retention_period(self):
        policy = ArtifactRetentionPolicy("30d")
        assert policy.max_age == "30d"
        assert policy.auto_cleanup is True

    def test_disabled_cleanup(self):
        policy = ArtifactRetentionPolicy("forever", auto_cleanup=False)
        assert policy.max_age == "forever"
        assert policy.auto_cleanup is False

    def test_invalid_retention_period_raises(self):
        with pytest.raises(ValueError, match="Invalid retention period"):
            ArtifactRetentionPolicy("invalid")

    def test_all_valid_periods(self):
        for period in ArtifactRetentionPolicy.VALID_PERIODS:
            policy = ArtifactRetentionPolicy(period)
            assert policy.max_age == period

    def test_short_retention(self):
        policy = ArtifactRetentionPolicy("1h")
        assert policy.max_age == "1h"

    def test_long_retention(self):
        policy = ArtifactRetentionPolicy("90d")
        assert policy.max_age == "90d"


class TestArtifactRetentionValidator:
    def setup_method(self):
        self.validator = ArtifactRetentionValidator()

    def test_add_valid_policy(self):
        policy = ArtifactRetentionPolicy("30d")
        self.validator.add_policy("logs", policy)
        assert "logs" in self.validator.list_policies()

    def test_rejects_auto_cleanup_with_forever(self):
        with pytest.raises(ValueError, match="auto_cleanup"):
            self.validator.add_policy("logs", ArtifactRetentionPolicy("forever", auto_cleanup=True))

    def test_allows_forever_without_auto_cleanup(self):
        self.validator.add_policy("logs", ArtifactRetentionPolicy("forever", auto_cleanup=False))

    def test_rejects_conflicting_policies(self):
        self.validator.add_policy("logs", ArtifactRetentionPolicy("30d"))
        with pytest.raises(ValueError, match="Conflicting"):
            self.validator.add_policy("logs", ArtifactRetentionPolicy("7d"))

    def test_accepts_same_policy_twice(self):
        self.validator.add_policy("logs", ArtifactRetentionPolicy("30d"))
        self.validator.add_policy("logs", ArtifactRetentionPolicy("30d"))  # same, no conflict

    def test_multiple_artifact_types(self):
        self.validator.add_policy("logs", ArtifactRetentionPolicy("7d"))
        self.validator.add_policy("metrics", ArtifactRetentionPolicy("90d"))
        self.validator.add_policy("snapshots", ArtifactRetentionPolicy("30d"))
        assert len(self.validator.list_policies()) == 3

    def test_validate_cleanup_schedule_passes(self):
        self.validator.add_policy("logs", ArtifactRetentionPolicy("7d"))
        self.validator.add_policy("backups", ArtifactRetentionPolicy("30d"))
        self.validator.validate_cleanup_schedule()  # should not raise

    def test_validate_cleanup_schedule_with_forever_no_auto(self):
        self.validator.add_policy("logs", ArtifactRetentionPolicy("forever", auto_cleanup=False))
        self.validator.validate_cleanup_schedule()  # should not raise


class TestWorkflowArtifactRetentionIntegration:
    def test_workflow_artifact_retention_policy(self):
        workflow = Workflow("test")
        policy = ArtifactRetentionPolicy("30d")
        workflow.add_artifact_retention_policy("logs", policy)
        assert "logs" in workflow.artifact_retention.list_policies()

    def test_workflow_validates_policies(self):
        workflow = Workflow("test")
        workflow.add_artifact_retention_policy("logs", ArtifactRetentionPolicy("7d"))
        workflow.validate_retention_policies()  # should not raise

    def test_workflow_rejects_invalid_retention_at_pre_dispatch(self):
        workflow = Workflow("test")
        with pytest.raises(ValueError, match="Invalid retention period"):
            workflow.add_artifact_retention_policy("logs", ArtifactRetentionPolicy("invalid-period"))

    def test_workflow_execution_with_retention_policies(self):
        manager = WorkflowManager()
        workflow = Workflow("test")
        workflow.add_artifact_retention_policy("logs", ArtifactRetentionPolicy("30d"))
        from unittest.mock import MagicMock
        step = MagicMock()
        step.name = "step1"
        step.handler.return_value = "done"
        workflow.add_step(step)

        manager._workflows[workflow.id] = workflow
        result = manager.execute_workflow(workflow.id)
        assert result is True
