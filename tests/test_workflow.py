"""Tests for artifact retention policy validation in cleanup scheduling."""

import time
import pytest
from src.orchestrator.workflow import (
    ArtifactRetentionCategory,
    ArtifactRetentionValidator,
    CleanupSchedule,
    WorkflowManager,
    WorkflowStep,
)


class TestCleanupSchedule:
    def test_eligible_at_default(self):
        now = time.time()
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=now,
            retention_seconds=3600,
        )
        assert schedule.eligible_at == now + 3600

    def test_is_overdue_false(self):
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=time.time() - 100,
            retention_seconds=86400,
        )
        assert not schedule.is_overdue

    def test_is_overdue_true(self):
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=time.time() - 7200,
            retention_seconds=1,
        )
        assert schedule.is_overdue

    def test_repr(self):
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.METRIC,
            created_at=1000.0,
            retention_seconds=3600,
        )
        r = repr(schedule)
        assert "metric" in r
        assert "3600" in r


class TestArtifactRetentionValidator:
    def setup_method(self):
        self.validator = ArtifactRetentionValidator()

    def test_valid_log_schedule(self):
        now = time.time()
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=now,
            retention_seconds=3600,
        )
        assert self.validator.validate_schedule(schedule)
        assert len(self.validator.violations) == 0

    def test_valid_checkpoint_schedule(self):
        now = time.time()
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.CHECKPOINT,
            created_at=now,
            retention_seconds=86400 * 30,
        )
        assert self.validator.validate_schedule(schedule)
        assert len(self.validator.violations) == 0

    def test_rejects_non_positive_retention(self):
        now = time.time()
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=now,
            retention_seconds=0,
        )
        assert not self.validator.validate_schedule(schedule)
        assert any("Non-positive" in v for v in self.validator.violations)

    def test_rejects_negative_retention(self):
        now = time.time()
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=now,
            retention_seconds=-1,
        )
        assert not self.validator.validate_schedule(schedule)
        assert any("Non-positive" in v for v in self.validator.violations)

    def test_rejects_excessive_retention(self):
        now = time.time()
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=now,
            retention_seconds=86400 * 100,  # 100 days, but LOG max is 7
        )
        assert not self.validator.validate_schedule(schedule)
        assert any("exceeds" in v for v in self.validator.violations)

    def test_rejects_future_timestamp(self):
        now = time.time()
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.RESULT,
            created_at=now + 3600,  # 1 hour in the future
            retention_seconds=86400,
        )
        assert not self.validator.validate_schedule(schedule)
        assert any("future" in v for v in self.validator.violations)

    def test_accepts_near_future_timestamp(self):
        now = time.time()
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.RESULT,
            created_at=now + 240,  # 4 minutes in the future (under 300s grace)
            retention_seconds=86400,
        )
        assert self.validator.validate_schedule(schedule)

    def test_rejects_already_overdue_with_short_retention(self):
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.TEMPORARY,
            created_at=time.time() - 7200,  # 2 hours ago
            retention_seconds=1800,  # 30 min — already overdue
        )
        assert not self.validator.validate_schedule(schedule)
        assert any("overdue" in v for v in self.validator.violations)

    def test_allows_overdue_with_long_retention(self):
        schedule = CleanupSchedule(
            category=ArtifactRetentionCategory.CHECKPOINT,
            created_at=time.time() - 7200,  # 2 hours ago
            retention_seconds=86400 * 30,  # 30 days
        )
        assert self.validator.validate_schedule(schedule)

    def test_violations_reset_between_validations(self):
        now = time.time()
        bad = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=now,
            retention_seconds=0,
        )
        good = CleanupSchedule(
            category=ArtifactRetentionCategory.LOG,
            created_at=now,
            retention_seconds=3600,
        )
        self.validator.validate_schedule(bad)
        assert len(self.validator.violations) > 0
        self.validator.validate_schedule(good)
        assert len(self.validator.violations) == 0

    def test_validate_workflow_all_valid(self):
        now = time.time()
        schedules = [
            CleanupSchedule(ArtifactRetentionCategory.LOG, now, 3600),
            CleanupSchedule(ArtifactRetentionCategory.RESULT, now, 86400),
        ]
        assert self.validator.validate_workflow("test-workflow", schedules)

    def test_validate_workflow_one_invalid(self):
        now = time.time()
        schedules = [
            CleanupSchedule(ArtifactRetentionCategory.LOG, now, 3600),
            CleanupSchedule(ArtifactRetentionCategory.LOG, now, 0),  # invalid
        ]
        assert not self.validator.validate_workflow("bad-workflow", schedules)


class TestWorkflowManagerRetention:
    def setup_method(self):
        self.manager = WorkflowManager()

    def test_register_workflow_valid_cleanup(self):
        now = time.time()
        schedules = [
            CleanupSchedule(ArtifactRetentionCategory.LOG, now, 3600),
            CleanupSchedule(ArtifactRetentionCategory.RESULT, now, 86400),
        ]
        wf = self.manager.register_workflow(
            "valid-workflow",
            "A workflow with valid cleanup schedules",
            schedules,
        )
        assert wf is not None
        assert wf.name == "valid-workflow"
        assert len(wf.cleanup_schedules) == 2

    def test_register_workflow_invalid_cleanup(self):
        now = time.time()
        schedules = [
            CleanupSchedule(ArtifactRetentionCategory.LOG, now, -1),  # invalid
        ]
        wf = self.manager.register_workflow(
            "invalid-workflow",
            "A workflow with invalid cleanup schedules",
            schedules,
        )
        assert wf is None

    def test_register_workflow_no_cleanup(self):
        wf = self.manager.register_workflow("no-cleanup", "No cleanup schedules")
        assert wf is not None
        assert len(wf.cleanup_schedules) == 0

    def test_add_cleanup_schedule_to_workflow(self):
        wf = self.manager.register_workflow("add-test", "Test adding schedules")
        assert wf is not None
        now = time.time()
        wf.add_cleanup_schedule(
            CleanupSchedule(ArtifactRetentionCategory.METRIC, now, 3600)
        )
        assert len(wf.cleanup_schedules) == 1

    def test_existing_create_workflow_maintains_backward_compat(self):
        wf = self.manager.create_workflow("old-style", "Uses old API")
        assert wf is not None
        assert isinstance(wf, object)
        assert self.manager.get_workflow(wf.id) is not None

# 2019-07-19T14:55:35 update

# 2020-02-10T13:24:54 update

# 2020-07-27T13:07:41 update

# 2020-11-11T15:16:49 update

# 2021-03-09T11:37:10 update

# 2021-10-06T13:05:33 update

# 2022-01-10T14:32:37 update

# 2022-07-27T12:31:16 update

# 2023-03-28T11:48:49 update

# 2023-09-01T13:47:51 update

# 2024-01-09T11:23:13 update

# 2024-07-16T13:52:38 update

# 2025-02-20T13:52:11 update

# 2025-08-26T11:11:49 update

# 2026-02-04T14:33:28 update

# 2026-05-10T12:41:47 update
