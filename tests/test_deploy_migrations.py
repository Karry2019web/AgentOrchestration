"""Tests for deploy/migrations.py — migration gate, compatibility checks, rollout readiness."""

import pytest
from src.deploy.migrations import (
    MigrationJob,
    MigrationRunner,
    MigrationCompatibility,
    MigrationStatus,
)


class TestMigrationJob:
    def test_successful_migration(self):
        job = MigrationJob("schema_v2", lambda: True)
        assert job.execute() is True
        assert job.status == MigrationStatus.COMPLETED
        assert job.error is None

    def test_failed_migration(self):
        job = MigrationJob("schema_v2", lambda: False)
        assert job.execute() is False
        assert job.status == MigrationStatus.FAILED
        assert job.error is not None

    def test_exception_during_migration(self):
        def crash():
            raise RuntimeError("DB connection lost")
        job = MigrationJob("crash", crash)
        assert job.execute() is False
        assert job.status == MigrationStatus.FAILED
        assert "DB connection lost" in (job.error or "")

    def test_compatibility_level(self):
        bc = MigrationJob("bc", lambda: True, MigrationCompatibility.FORWARD_COMPATIBLE)
        assert bc.compatibility == MigrationCompatibility.FORWARD_COMPATIBLE


class TestMigrationRunner:
    def test_run_all_success(self):
        runner = MigrationRunner()
        runner.register(MigrationJob("m1", lambda: True))
        runner.register(MigrationJob("m2", lambda: True))
        assert runner.run_all() is True
        summary = runner.summary()
        assert summary["total"] == 2
        assert summary["completed"] == 2
        assert summary["failed"] == 0

    def test_run_all_partial_failure(self):
        runner = MigrationRunner()
        runner.register(MigrationJob("good", lambda: True))
        runner.register(MigrationJob("bad", lambda: False))
        assert runner.run_all() is False
        summary = runner.summary()
        assert summary["completed"] == 1
        assert summary["failed"] == 1
        assert summary["failed_jobs"] == ["bad"]

    def test_rollout_ready_all_pass(self):
        runner = MigrationRunner()
        runner.register(MigrationJob("m1", lambda: True))
        runner.run_all()
        ready, msg = runner.is_rollout_ready()
        assert ready is True
        assert "proceed" in msg.lower()

    def test_rollout_blocked_on_failure(self):
        runner = MigrationRunner()
        runner.register(MigrationJob("fail", lambda: False))
        runner.run_all()
        ready, msg = runner.is_rollout_ready()
        assert ready is False
        assert "blocked" in msg.lower()

    def test_rollout_ready_no_migrations(self):
        runner = MigrationRunner()
        ready, msg = runner.is_rollout_ready()
        assert ready is True
        assert "no migrations" in msg.lower()


class TestRolloutGate:
    """End-to-end: simulate a deploy with migration gate."""

    def test_full_rollout_flow_success(self):
        runner = MigrationRunner()
        runner.register(MigrationJob("create_table", lambda: True))
        runner.register(MigrationJob("add_index", lambda: True))
        assert runner.run_all() is True
        ready, msg = runner.is_rollout_ready()
        assert ready is True

    def test_full_rollout_flow_failure_keeps_old_version(self):
        runner = MigrationRunner()
        runner.register(MigrationJob("safe_change", lambda: True))
        runner.register(MigrationJob("dangerous_change", lambda: False))
        assert runner.run_all() is False
        ready, _ = runner.is_rollout_ready()
        # Rollout is blocked — old version keeps serving
        assert ready is False
