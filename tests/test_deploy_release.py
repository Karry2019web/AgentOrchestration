"""Tests for deployment migration release gate."""

from src.deploy import (
    ApplicationRolloutSpec,
    MigrationCompatibility,
    MigrationJobResult,
    check_migration_compatibility,
    evaluate_release_gate,
)


def test_rollout_waits_until_migration_completes():
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-1",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="add-task-state-index",
            completed=False,
            succeeded=False,
            compatibility=MigrationCompatibility(
                backward_compatible=True,
                reversible=True,
            ),
        ),
    )

    assert decision.allow_new_version is False
    assert decision.serving_version == "app:v1"
    assert "not completed" in decision.blocked_reason


def test_migration_failure_keeps_prior_version_serving():
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-2",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="alter-task-state",
            completed=True,
            succeeded=False,
            compatibility=MigrationCompatibility(
                backward_compatible=True,
                reversible=True,
            ),
        ),
    )

    assert decision.allow_new_version is False
    assert decision.serving_version == "app:v1"
    assert "failed" in decision.blocked_reason


def test_incompatible_reversible_release_is_blocked_and_reported():
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-3",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="drop-legacy-task-column",
            completed=True,
            succeeded=True,
            compatibility=MigrationCompatibility(
                backward_compatible=False,
                reversible=False,
                details="drops a column still read by v1 workers",
            ),
        ),
    )

    assert decision.allow_new_version is False
    assert decision.serving_version == "app:v1"
    assert decision.checks["backward_compatible"] is False
    assert decision.checks["reversible"] is False
    assert "not backward compatible" in decision.blocked_reason


def test_successful_compatible_migration_allows_target_traffic():
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-4",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="add-nullable-task-state-column",
            completed=True,
            succeeded=True,
            compatibility=MigrationCompatibility(
                backward_compatible=True,
                reversible=True,
            ),
        ),
    )

    assert decision.allow_new_version is True
    assert decision.serving_version == "app:v2"
    assert decision.blocked_reason is None


def test_release_checks_identify_backward_compatibility():
    checks = check_migration_compatibility(
        MigrationJobResult(
            name="rename-task-state-column",
            completed=True,
            succeeded=True,
            compatibility=MigrationCompatibility(
                backward_compatible=False,
                reversible=True,
                details="rename needs a dual-read release first",
            ),
        )
    )

    assert checks["migration_completed"] is True
    assert checks["migration_succeeded"] is True
    assert checks["backward_compatible"] is False
    assert checks["details"] == "rename needs a dual-read release first"


def test_irreversible_migration_blocked_when_required():
    """When require_reversible_migration=True, non-reversible migrations block rollout."""
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-5",
            previous_version="app:v1",
            target_version="app:v2",
            require_reversible_migration=True,
        ),
        MigrationJobResult(
            name="drop-task-table",
            completed=True,
            succeeded=True,
            compatibility=MigrationCompatibility(
                backward_compatible=True,
                reversible=False,
                details="drop operation cannot be reversed",
            ),
        ),
    )

    assert decision.allow_new_version is False
    assert decision.serving_version == "app:v1"
    assert "not reversible" in decision.blocked_reason
    assert decision.checks["reversible"] is False


def test_irreversible_migration_allowed_when_not_required():
    """When require_reversible_migration=False, non-reversible migrations are allowed."""
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-6",
            previous_version="app:v1",
            target_version="app:v2",
            require_reversible_migration=False,
        ),
        MigrationJobResult(
            name="drop-task-table",
            completed=True,
            succeeded=True,
            compatibility=MigrationCompatibility(
                backward_compatible=True,
                reversible=False,
                details="drop operation cannot be reversed",
            ),
        ),
    )

    assert decision.allow_new_version is True
    assert decision.serving_version == "app:v2"
    assert decision.blocked_reason is None


def test_missing_compatibility_blocks_rollout():
    """A migration job with no compatibility assessment blocks the rollout."""
    decision = evaluate_release_gate(
        ApplicationRolloutSpec(
            release_id="release-7",
            previous_version="app:v1",
            target_version="app:v2",
        ),
        MigrationJobResult(
            name="unknown-migration",
            completed=True,
            succeeded=True,
            compatibility=None,
        ),
    )

    assert decision.allow_new_version is False
    assert decision.serving_version == "app:v1"
    assert "compatibility check is missing" in decision.blocked_reason


def test_in_flight_migration_has_no_compatibility_check_yet():
    """A migration that has not yet run has null compatibility fields."""
    migration = MigrationJobResult(
        name="pending-migration",
        completed=False,
        succeeded=False,
        compatibility=None,
    )
    checks = check_migration_compatibility(migration)

    assert checks["migration_completed"] is False
    assert checks["migration_succeeded"] is False
    assert checks["backward_compatible"] is None
    assert checks["reversible"] is None


def test_rollout_spec_has_expected_default():
    """ApplicationRolloutSpec defaults to requiring reversible migrations."""
    spec = ApplicationRolloutSpec(
        release_id="default-test",
        previous_version="app:v1",
        target_version="app:v2",
    )
    assert spec.require_reversible_migration is True
