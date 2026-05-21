"""Tests for deploy preflight module."""

import time
import pytest
from src.deploy.preflight import (
    MigrationMetadata,
    BackupVerification,
    MigrationPreflight,
    DestructiveMigrationError,
)


class TestMigrationMetadata:
    def test_non_destructive_default(self):
        meta = MigrationMetadata(name="add_index", description="Add an index")
        assert meta.destructive is False
        assert meta.backup_required is True

    def test_destructive_migration(self):
        meta = MigrationMetadata(name="drop_table", description="Drop deprecated table", destructive=True)
        assert meta.destructive is True

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            MigrationMetadata(name="", description="empty")

    def test_whitespace_name_raises(self):
        with pytest.raises(ValueError):
            MigrationMetadata(name="   ", description="spaces")


class TestBackupVerification:
    def test_fresh_backup(self):
        v = BackupVerification(backup_timestamp=time.time() - 3600, restore_verified=True)
        assert v.is_fresh is True
        assert v.passed is True

    def test_stale_backup(self):
        v = BackupVerification(backup_timestamp=time.time() - 90000, restore_verified=True)
        assert v.is_fresh is False

    def test_no_backup(self):
        v = BackupVerification()
        assert v.is_fresh is False
        assert v.passed is False

    def test_restore_not_verified(self):
        v = BackupVerification(backup_timestamp=time.time() - 100, restore_verified=False)
        assert v.passed is False

    def test_with_errors(self):
        v = BackupVerification(
            backup_timestamp=time.time() - 100,
            restore_verified=True,
            errors=["checksum mismatch"],
        )
        assert v.passed is False


class TestMigrationPreflight:
    def setup_method(self):
        self.preflight = MigrationPreflight()
        self.preflight.register_backup("backup-001", time.time() - 100)
        self.preflight.verify_restore("backup-001", success=True)

    def test_non_destructive_passes(self):
        migration = MigrationMetadata(name="add_column", description="Add a column")
        result = self.preflight.check(migration)
        assert result.passed is True

    def test_destructive_with_valid_backup(self):
        migration = MigrationMetadata(name="drop_column", description="Drop column", destructive=True)
        result = self.preflight.check(migration, backup_id="backup-001")
        assert result.passed is True
        assert result.restore_verified is True

    def test_destructive_without_backup_id(self):
        migration = MigrationMetadata(name="drop_table", description="Drop", destructive=True)
        with pytest.raises(DestructiveMigrationError, match="No backup ID"):
            self.preflight.check(migration)

    def test_destructive_with_missing_backup(self):
        migration = MigrationMetadata(name="drop", description="Drop", destructive=True)
        with pytest.raises(DestructiveMigrationError, match="No backup registered"):
            self.preflight.check(migration, backup_id="nonexistent")

    def test_destructive_with_stale_backup(self):
        self.preflight.register_backup("backup-old", time.time() - 200000)
        self.preflight.verify_restore("backup-old", success=True)
        migration = MigrationMetadata(name="drop", description="Drop", destructive=True)
        with pytest.raises(DestructiveMigrationError, match="stale|old"):
            self.preflight.check(migration, backup_id="backup-old")

    def test_destructive_with_unverified_restore(self):
        self.preflight.register_backup("backup-002", time.time() - 100)
        # Not calling verify_restore
        migration = MigrationMetadata(name="drop", description="Drop", destructive=True)
        with pytest.raises(DestructiveMigrationError, match="verification failed|missing"):
            self.preflight.check(migration, backup_id="backup-002")

    def test_destructive_with_failed_restore(self):
        self.preflight.register_backup("backup-003", time.time() - 100)
        self.preflight.verify_restore("backup-003", success=False, errors=["checksum mismatch"])
        migration = MigrationMetadata(name="drop", description="Drop", destructive=True)
        with pytest.raises(DestructiveMigrationError):
            self.preflight.check(migration, backup_id="backup-003")

    def test_report_non_destructive(self):
        migration = MigrationMetadata(name="safe_migration", description="Safe")
        report = self.preflight.report(migration)
        assert "PASSED" in report

    def test_report_blocked(self):
        migration = MigrationMetadata(name="risky", description="Risky", destructive=True)
        report = self.preflight.report(migration, backup_id="nonexistent")
        assert "BLOCKED" in report
