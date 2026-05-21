"""Migration preflight — backup freshness verification for destructive migrations."""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MigrationMetadata:
    """Declares whether a database migration is destructive."""

    name: str
    description: str
    destructive: bool = False
    backup_required: bool = True

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("Migration name must not be empty")


@dataclass
class BackupVerification:
    """Result of a backup freshness and restore check."""

    backup_timestamp: Optional[float] = None
    restore_verified: bool = False
    errors: list = field(default_factory=list)
    verified_at: float = field(default_factory=time.time)

    @property
    def is_fresh(self) -> bool:
        """Backup is considered fresh if created within the last 24 hours."""
        if self.backup_timestamp is None:
            return False
        return (time.time() - self.backup_timestamp) < 86400

    @property
    def passed(self) -> bool:
        """Preflight passes if backup exists, is fresh, and restore was verified."""
        return self.backup_timestamp is not None and self.is_fresh and self.restore_verified and not self.errors


class DestructiveMigrationError(Exception):
    """Raised when a destructive migration fails its preflight checks."""

    def __init__(self, migration_name: str, reason: str):
        self.migration_name = migration_name
        self.reason = reason
        super().__init__(f"Destructive migration '{migration_name}' blocked: {reason}")


class MigrationPreflight:
    """Preflight gate that enforces backup freshness before destructive migrations."""

    MAX_BACKUP_AGE_SECONDS = 86400  # 24 hours

    def __init__(self):
        self._backups: dict = {}
        self._restore_checks: dict = {}

    def register_backup(self, backup_id: str, timestamp: Optional[float] = None) -> None:
        """Register a backup with its creation timestamp."""
        self._backups[backup_id] = timestamp or time.time()

    def verify_restore(self, backup_id: str, success: bool = True, errors: Optional[list] = None) -> None:
        """Record the result of a restore verification for a backup."""
        self._restore_checks[backup_id] = {
            "success": success,
            "errors": errors or [],
            "verified_at": time.time(),
        }

    def check(self, migration: MigrationMetadata, backup_id: Optional[str] = None) -> BackupVerification:
        """Run the preflight check for a migration.

        For non-destructive migrations, this always passes.
        For destructive migrations, a fresh and verified backup is required.
        """
        if not migration.destructive:
            return BackupVerification(
                backup_timestamp=time.time(),
                restore_verified=True,
            )

        if not backup_id:
            raise DestructiveMigrationError(
                migration.name,
                "No backup ID provided for destructive migration preflight"
            )

        timestamp = self._backups.get(backup_id)
        if timestamp is None:
            raise DestructiveMigrationError(
                migration.name,
                f"No backup registered: {backup_id}"
            )

        backup_age = time.time() - timestamp
        if backup_age > self.MAX_BACKUP_AGE_SECONDS:
            raise DestructiveMigrationError(
                migration.name,
                f"Backup {backup_id} is {backup_age:.0f}s old (max {self.MAX_BACKUP_AGE_SECONDS}s)"
            )

        restore_info = self._restore_checks.get(backup_id, {})
        if not restore_info.get("success", False):
            raise DestructiveMigrationError(
                migration.name,
                f"Restore verification failed or missing for backup {backup_id}"
            )

        return BackupVerification(
            backup_timestamp=timestamp,
            restore_verified=True,
            verified_at=time.time(),
        )

    def report(self, migration: MigrationMetadata, backup_id: Optional[str] = None) -> str:
        """Format a human-readable preflight report."""
        try:
            result = self.check(migration, backup_id)
            lines = [
                f"Migration: {migration.name}",
                f"  Destructive: {migration.destructive}",
                f"  Backup timestamp: {result.backup_timestamp}",
                f"  Restore verified: {result.restore_verified}",
                f"  Status: PASSED",
            ]
        except DestructiveMigrationError as e:
            lines = [
                f"Migration: {migration.name}",
                f"  Destructive: {migration.destructive}",
                f"  Status: BLOCKED",
                f"  Reason: {e.reason}",
            ]
        return "\n".join(lines)
