"""Tests for dataset export consent gate pipeline."""

import time
import pytest
from src.orchestrator.dataset import (
    ConsentStatus,
    ExportPurpose,
    WorkspaceConsent,
    TaskRecord,
    DatasetExportPipeline,
)


class TestConsentStatus:
    def test_granted_permits_purpose(self):
        consent = WorkspaceConsent(
            workspace_id="ws-1",
            status=ConsentStatus.GRANTED,
            granted_purposes={ExportPurpose.TRAINING},
        )
        assert consent.permits(ExportPurpose.TRAINING) is True
        assert consent.permits(ExportPurpose.EVALUATION) is False

    def test_denied_blocks_all(self):
        consent = WorkspaceConsent(
            workspace_id="ws-2",
            status=ConsentStatus.DENIED,
        )
        assert consent.permits(ExportPurpose.TRAINING) is False
        assert consent.permits(ExportPurpose.EVALUATION) is False

    def test_unspecified_blocks_all(self):
        consent = WorkspaceConsent(
            workspace_id="ws-3",
            status=ConsentStatus.UNSPECIFIED,
        )
        assert consent.permits(ExportPurpose.TRAINING) is False

    def test_partial_purpose_grant(self):
        consent = WorkspaceConsent(
            workspace_id="ws-4",
            status=ConsentStatus.GRANTED,
            granted_purposes={ExportPurpose.EVALUATION},
        )
        assert consent.permits(ExportPurpose.TRAINING) is False
        assert consent.permits(ExportPurpose.EVALUATION) is True
        assert consent.permits(ExportPurpose.BENCHMARKING) is False


class TestDatasetExportPipeline:
    def setup_method(self):
        self.pipeline = DatasetExportPipeline()
        self._seed_data()

    def _seed_data(self):
        """Set up consent states and records for testing."""
        # Workspace 1: full training + evaluation consent
        self.pipeline.set_workspace_consent(
            "ws-consenting",
            ConsentStatus.GRANTED,
            [ExportPurpose.TRAINING, ExportPurpose.EVALUATION],
        )
        # Workspace 2: evaluation only
        self.pipeline.set_workspace_consent(
            "ws-eval-only",
            ConsentStatus.GRANTED,
            [ExportPurpose.EVALUATION],
        )
        # Workspace 3: opted out
        self.pipeline.set_workspace_consent(
            "ws-opted-out",
            ConsentStatus.DENIED,
        )
        # Workspace 4: no consent set (unspecified)
        # (No consent entry - should be treated as excluded)

        # Add records
        self.pipeline.add_record(TaskRecord(
            task_id="task-1", workspace_id="ws-consenting",
            agent_id="agent-a", task_type="inference",
            payload={}, result={},
            created_at=time.time(), updated_at=time.time(),
        ))
        self.pipeline.add_record(TaskRecord(
            task_id="task-2", workspace_id="ws-consenting",
            agent_id="agent-a", task_type="training",
            payload={}, result={},
            created_at=time.time(), updated_at=time.time(),
        ))
        self.pipeline.add_record(TaskRecord(
            task_id="task-3", workspace_id="ws-eval-only",
            agent_id="agent-b", task_type="evaluation",
            payload={}, result={},
            created_at=time.time(), updated_at=time.time(),
        ))
        self.pipeline.add_record(TaskRecord(
            task_id="task-4", workspace_id="ws-opted-out",
            agent_id="agent-c", task_type="inference",
            payload={}, result={},
            created_at=time.time(), updated_at=time.time(),
        ))
        self.pipeline.add_record(TaskRecord(
            task_id="task-5", workspace_id="ws-noconsent",
            agent_id="agent-d", task_type="inference",
            payload={}, result={},
            created_at=time.time(), updated_at=time.time(),
        ))

    def test_select_records_training(self):
        """Training export should include ws-consenting only."""
        selected = self.pipeline.select_records(ExportPurpose.TRAINING)
        record_ids = [r.task_id for r in selected]
        assert "task-1" in record_ids
        assert "task-2" in record_ids
        assert "task-3" not in record_ids  # eval-only workspace
        assert "task-4" not in record_ids  # opted out
        assert "task-5" not in record_ids  # no consent

    def test_select_records_evaluation(self):
        """Evaluation export should include both consenting and eval-only."""
        selected = self.pipeline.select_records(ExportPurpose.EVALUATION)
        record_ids = [r.task_id for r in selected]
        assert "task-1" in record_ids   # ws-consenting (has eval)
        assert "task-2" in record_ids   # ws-consenting (has eval)
        assert "task-3" in record_ids   # ws-eval-only
        assert "task-4" not in record_ids  # opted out
        assert "task-5" not in record_ids  # no consent

    def test_export_creates_manifest(self):
        """Export should produce a manifest with selection metadata."""
        manifest = self.pipeline.export(ExportPurpose.TRAINING)
        assert manifest.manifest_id is not None
        assert manifest.purpose == ExportPurpose.TRAINING
        assert manifest.total_records == 2  # only ws-consenting records
        assert "ws-consenting" in manifest.included_workspaces
        assert "ws-eval-only" in manifest.excluded_workspaces
        assert "ws-opted-out" in manifest.excluded_workspaces
        assert manifest.consent_criteria["purpose"] == "training"
        assert manifest.consent_criteria["required_consent"] == "granted"
        assert len(manifest.record_ids) == 2

    def test_export_excludes_workspaces_without_consent(self):
        """Manifest should list all excluded workspaces."""
        manifest = self.pipeline.export(ExportPurpose.EVALUATION)
        # ws-eval-only should be included (has eval consent)
        assert "ws-eval-only" in manifest.included_workspaces
        assert "ws-consenting" in manifest.included_workspaces
        # ws-opted-out and ws-noconsent should be excluded
        assert "ws-opted-out" in manifest.excluded_workspaces

    def test_revoke_consent_before_export(self):
        """Revoking consent mid-cycle should affect export."""
        self.pipeline.revoke_workspace_consent("ws-consenting")
        selected = self.pipeline.select_records(ExportPurpose.TRAINING)
        assert len(selected) == 0

    def test_manifest_idempotency(self):
        """Multiple exports should produce separate manifests."""
        m1 = self.pipeline.export(ExportPurpose.TRAINING)
        m2 = self.pipeline.export(ExportPurpose.TRAINING)
        assert m1.manifest_id != m2.manifest_id

    def test_get_manifest(self):
        """Manifests should be retrievable by ID."""
        manifest = self.pipeline.export(ExportPurpose.TRAINING)
        retrieved = self.pipeline.get_manifest(manifest.manifest_id)
        assert retrieved is not None
        assert retrieved.manifest_id == manifest.manifest_id

    def test_list_manifests(self):
        """Pipeline should list all recorded manifests."""
        self.pipeline.export(ExportPurpose.TRAINING)
        self.pipeline.export(ExportPurpose.EVALUATION)
        manifests = self.pipeline.list_manifests()
        assert len(manifests) == 2

    def test_opt_out_change_before_scheduled_export(self):
        """Opt-out changes before scheduled exports should be respected."""
        # Initially consenting workspace opts out
        self.pipeline.set_workspace_consent(
            "ws-consenting",
            ConsentStatus.DENIED,
        )
        selected = self.pipeline.select_records(ExportPurpose.TRAINING)
        assert len(selected) == 0

    def test_empty_pipeline_export(self):
        """Export with no records should produce empty manifest."""
        empty_pipeline = DatasetExportPipeline()
        manifest = empty_pipeline.export(ExportPurpose.TRAINING)
        assert manifest.total_records == 0
        assert len(manifest.record_ids) == 0
