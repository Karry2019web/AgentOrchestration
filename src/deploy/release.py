"""Migration gates for database-backed application rollouts.

Provides a release gate that blocks new application pods from receiving
traffic until required database migrations complete and pass
compatibility checks.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class MigrationCompatibility:
    """Compatibility assessment for a pending database migration."""

    backward_compatible: bool
    reversible: bool
    details: str = ""


@dataclass(frozen=True)
class MigrationJobResult:
    """Observed state of the migration job that gates rollout traffic."""

    name: str
    completed: bool
    succeeded: bool
    compatibility: Optional[MigrationCompatibility] = None


@dataclass(frozen=True)
class ApplicationRolloutSpec:
    """Application release versions controlled by the migration gate."""

    release_id: str
    previous_version: str
    target_version: str
    require_reversible_migration: bool = True


@dataclass(frozen=True)
class ReleaseGateDecision:
    """Decision describing which application version may receive traffic."""

    release_id: str
    allow_new_version: bool
    serving_version: str
    blocked_reason: Optional[str]
    checks: Dict[str, object]


def check_migration_compatibility(
    migration: MigrationJobResult,
) -> Dict[str, object]:
    """Return release checks that describe migration safety."""

    compatibility = migration.compatibility
    checks: Dict[str, object] = {
        "migration_name": migration.name,
        "migration_completed": migration.completed,
        "migration_succeeded": migration.succeeded,
        "backward_compatible": None,
        "reversible": None,
        "details": "",
    }
    if compatibility is not None:
        checks.update(
            {
                "backward_compatible": compatibility.backward_compatible,
                "reversible": compatibility.reversible,
                "details": compatibility.details,
            }
        )
    return checks


def evaluate_release_gate(
    rollout: ApplicationRolloutSpec,
    migration: MigrationJobResult,
) -> ReleaseGateDecision:
    """Block rollout traffic until migrations pass required safety checks."""

    checks = check_migration_compatibility(migration)
    blockers = _migration_blockers(rollout, migration)
    if blockers:
        return ReleaseGateDecision(
            release_id=rollout.release_id,
            allow_new_version=False,
            serving_version=rollout.previous_version,
            blocked_reason="; ".join(blockers),
            checks=checks,
        )

    return ReleaseGateDecision(
        release_id=rollout.release_id,
        allow_new_version=True,
        serving_version=rollout.target_version,
        blocked_reason=None,
        checks=checks,
    )


def _migration_blockers(
    rollout: ApplicationRolloutSpec,
    migration: MigrationJobResult,
) -> List[str]:
    blockers: List[str] = []
    if not migration.completed:
        blockers.append("migration job has not completed")
    if migration.completed and not migration.succeeded:
        blockers.append("migration job failed")
    if migration.compatibility is None:
        blockers.append("migration compatibility check is missing")
        return blockers

    compatibility = migration.compatibility
    if rollout.require_reversible_migration and not compatibility.reversible:
        blockers.append("migration is not reversible")
    if not compatibility.backward_compatible:
        blockers.append("migration is not backward compatible")
    return blockers
