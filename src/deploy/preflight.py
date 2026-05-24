"""Deploy Preflight — backup freshness verification before destructive migrations.

This module provides a preflight gate that checks:
1. Whether a migration is declared as destructive.
2. Whether a recent verified backup exists.
3. The restore-verification status of the backup.
"""

import datetime
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

BACKUP_FRESHNESS_HOURS = 24  # Default: backup must be within 24 hours


class MigrationSeverity(Enum):
    """Declared severity of a database migration."""
    SAFE = "safe"
    DESTRUCTIVE = "destructive"


class PreflightStatus(Enum):
    """Result status of a preflight check."""
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class BackupRecord:
    """Metadata about a restorable backup."""
    timestamp: datetime.datetime
    restore_verified: bool
    backup_id: str = ""


@dataclass
class PreflightResult:
    """Result of a preflight gate check."""
    status: PreflightStatus
    backup_timestamp: Optional[datetime.datetime] = None
    restore_check_status: Optional[bool] = None
    message: str = ""


def check_backup_freshness(
    backup: Optional[BackupRecord],
    max_age_hours: int = BACKUP_FRESHNESS_HOURS,
) -> PreflightResult:
    """Check whether a backup exists, is fresh enough, and has been restore-verified.

    Args:
        backup: The backup record to validate, or None if no backup exists.
        max_age_hours: Maximum allowed age of the backup in hours.

    Returns:
        PreflightResult with PASS if the backup is fresh and verified,
        FAIL otherwise.
    """
    if backup is None:
        return PreflightResult(
            status=PreflightStatus.FAIL,
            message="No backup found. A verified backup is required before destructive migrations.",
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    age = now - backup.timestamp

    if age > datetime.timedelta(hours=max_age_hours):
        return PreflightResult(
            status=PreflightStatus.FAIL,
            backup_timestamp=backup.timestamp,
            restore_check_status=backup.restore_verified,
            message=(
                f"Backup is too old ({age.total_seconds() / 3600:.1f}h old). "
                f"Maximum allowed age is {max_age_hours}h. "
                f"Backup ID: {backup.backup_id or 'unknown'}."
            ),
        )

    if not backup.restore_verified:
        return PreflightResult(
            status=PreflightStatus.FAIL,
            backup_timestamp=backup.timestamp,
            restore_check_status=False,
            message=(
                f"Backup found (age: {age.total_seconds() / 3600:.1f}h) but restore "
                f"verification has not been performed. "
                f"Backup ID: {backup.backup_id or 'unknown'}."
            ),
        )

    return PreflightResult(
        status=PreflightStatus.PASS,
        backup_timestamp=backup.timestamp,
        restore_check_status=True,
        message=(
            f"Backup is fresh (age: {age.total_seconds() / 3600:.1f}h) "
            f"and restore-verified. Backup ID: {backup.backup_id or 'unknown'}."
        ),
    )


def run_preflight(
    migration_severity: MigrationSeverity,
    backup: Optional[BackupRecord] = None,
    max_age_hours: int = BACKUP_FRESHNESS_HOURS,
) -> PreflightResult:
    """Run the full preflight gate before a migration.

    For SAFE migrations the check is skipped. For DESTRUCTIVE migrations
    the backup freshness is verified.

    Args:
        migration_severity: Whether the migration is SAFE or DESTRUCTIVE.
        backup: The current backup record (None if unavailable).
        max_age_hours: Max backup age in hours.

    Returns:
        PreflightResult indicating pass, fail, or skip.
    """
    if migration_severity == MigrationSeverity.SAFE:
        logger.info("Migration is SAFE — skipping backup freshness check.")
        return PreflightResult(
            status=PreflightStatus.PASS,
            message="Non-destructive migration — no backup freshness check required.",
        )

    if migration_severity == MigrationSeverity.DESTRUCTIVE:
        logger.warning("Migration is DESTRUCTIVE — verifying backup freshness.")
        return check_backup_freshness(backup, max_age_hours)

    return PreflightResult(
        status=PreflightStatus.FAIL,
        message=f"Unknown migration severity: {migration_severity}",
    )
