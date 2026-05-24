"""Tests for deploy preflight — backup freshness gate."""

import datetime

import pytest

from src.deploy.preflight import (
    BACKUP_FRESHNESS_HOURS,
    BackupRecord,
    MigrationSeverity,
    PreflightResult,
    PreflightStatus,
    check_backup_freshness,
    run_preflight,
)


class TestCheckBackupFreshness:
    def test_no_backup_returns_fail(self):
        result = check_backup_freshness(None)
        assert result.status == PreflightStatus.FAIL
        assert "No backup found" in result.message

    def test_fresh_verified_backup_returns_pass(self):
        backup = BackupRecord(
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            restore_verified=True,
            backup_id="backup-001",
        )
        result = check_backup_freshness(backup)
        assert result.status == PreflightStatus.PASS
        assert result.restore_check_status is True
        assert result.backup_timestamp is not None
        assert "fresh" in result.message.lower()

    def test_stale_backup_returns_fail(self):
        stale_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
        backup = BackupRecord(
            timestamp=stale_time,
            restore_verified=True,
            backup_id="backup-002",
        )
        result = check_backup_freshness(backup)
        assert result.status == PreflightStatus.FAIL
        assert "too old" in result.message.lower()

    def test_backup_not_restore_verified_returns_fail(self):
        backup = BackupRecord(
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            restore_verified=False,
            backup_id="backup-003",
        )
        result = check_backup_freshness(backup)
        assert result.status == PreflightStatus.FAIL
        assert "restore verification" in result.message.lower()
        assert result.restore_check_status is False

    def test_custom_max_age_hours(self):
        backup = BackupRecord(
            timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12),
            restore_verified=True,
            backup_id="backup-004",
        )
        # 12h old, but max age is 6h -> should fail
        result = check_backup_freshness(backup, max_age_hours=6)
        assert result.status == PreflightStatus.FAIL
        assert "too old" in result.message.lower()

    def test_fresh_backup_within_custom_window(self):
        backup = BackupRecord(
            timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4),
            restore_verified=True,
            backup_id="backup-005",
        )
        result = check_backup_freshness(backup, max_age_hours=6)
        assert result.status == PreflightStatus.PASS


class TestRunPreflight:
    def test_safe_migration_skips_check(self):
        result = run_preflight(MigrationSeverity.SAFE)
        assert result.status == PreflightStatus.PASS
        assert "Non-destructive" in result.message

    def test_safe_migration_no_backup_needed(self):
        result = run_preflight(MigrationSeverity.SAFE, backup=None)
        assert result.status == PreflightStatus.PASS

    def test_destructive_without_backup_fails(self):
        result = run_preflight(MigrationSeverity.DESTRUCTIVE)
        assert result.status == PreflightStatus.FAIL
        assert "No backup found" in result.message

    def test_destructive_with_fresh_backup_passes(self):
        backup = BackupRecord(
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            restore_verified=True,
            backup_id="backup-006",
        )
        result = run_preflight(MigrationSeverity.DESTRUCTIVE, backup)
        assert result.status == PreflightStatus.PASS

    def test_destructive_with_stale_backup_fails(self):
        stale_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
        backup = BackupRecord(
            timestamp=stale_time,
            restore_verified=True,
            backup_id="backup-007",
        )
        result = run_preflight(MigrationSeverity.DESTRUCTIVE, backup)
        assert result.status == PreflightStatus.FAIL
        assert "too old" in result.message
        assert result.backup_timestamp == stale_time

    def test_destructive_with_unverified_backup_fails(self):
        backup = BackupRecord(
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            restore_verified=False,
            backup_id="backup-008",
        )
        result = run_preflight(MigrationSeverity.DESTRUCTIVE, backup)
        assert result.status == PreflightStatus.FAIL
        assert result.restore_check_status is False
