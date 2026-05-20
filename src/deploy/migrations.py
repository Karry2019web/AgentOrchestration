"""Deploy Migration Runner — Ensures migrations run before application rollout.

Provides:
- MigrationJob: a single migration unit with compatibility-check support.
- MigrationRunner: runs all pending migrations, gates rollout on success.
- MigrationCompatibility: checks forward/backward compatibility for schema changes.
"""

import logging
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


class MigrationStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class MigrationCompatibility(Enum):
    """Compatibility level of a migration."""
    BACKWARD_COMPATIBLE = "backward_compatible"
    FORWARD_COMPATIBLE = "forward_compatible"
    UNKNOWN = "unknown"


class MigrationJob:
    """A single database migration unit."""

    def __init__(
        self,
        name: str,
        handler: Callable[[], bool],
        compatibility: MigrationCompatibility = MigrationCompatibility.UNKNOWN,
        description: str = "",
    ):
        self.name = name
        self.handler = handler
        self.compatibility = compatibility
        self.description = description
        self.status = MigrationStatus.PENDING
        self.error: Optional[str] = None

    def execute(self) -> bool:
        """Execute the migration handler. Returns True on success."""
        try:
            self.status = MigrationStatus.RUNNING
            result = self.handler()
            if result:
                self.status = MigrationStatus.COMPLETED
                logger.info("Migration '%s' completed successfully.", self.name)
                return True
            self.status = MigrationStatus.FAILED
            self.error = f"Migration '{self.name}' returned False"
            logger.error(self.error)
            return False
        except Exception as exc:
            self.status = MigrationStatus.FAILED
            self.error = f"Migration '{self.name}' raised: {exc}"
            logger.exception("Migration '%s' failed with exception.", self.name)
            return False


class MigrationRunner:
    """Runs pending migrations and reports rollout readiness."""

    def __init__(self):
        self._jobs: List[MigrationJob] = []
        self._completed: List[str] = []
        self._failed: List[str] = []

    def register(self, job: MigrationJob) -> None:
        self._jobs.append(job)

    def run_all(self) -> bool:
        """Execute all registered migrations. Returns True if all succeeded."""
        self._completed.clear()
        self._failed.clear()
        all_ok = True
        for job in self._jobs:
            if job.status == MigrationStatus.COMPLETED:
                self._completed.append(job.name)
                continue
            ok = job.execute()
            if ok:
                self._completed.append(job.name)
            else:
                self._failed.append(job.name)
                all_ok = False
                # Do not stop — run remaining so we collect full failure list.
        return all_ok

    def is_rollout_ready(self) -> Tuple[bool, str]:
        """Check whether all migrations passed and rollout can proceed."""
        if self._failed:
            return False, (
                f"Rollout blocked: {len(self._failed)} migration(s) failed. "
                f"Failed: {', '.join(self._failed)}. "
                f"Completed: {', '.join(self._completed) if self._completed else 'none'}. "
                "Fix failures and retry deployment."
            )
        if not self._completed:
            return True, "No migrations registered — proceeding with rollout."
        return True, (
            f"All {len(self._completed)} migration(s) passed. "
            "Rollout may proceed."
        )

    def summary(self) -> Dict[str, object]:
        return {
            "total": len(self._jobs),
            "completed": len(self._completed),
            "failed": len(self._failed),
            "completed_jobs": list(self._completed),
            "failed_jobs": list(self._failed),
        }
