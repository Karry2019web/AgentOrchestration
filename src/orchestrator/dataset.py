"""Dataset Export Pipeline — Consent-gated training data selection."""

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


class ConsentStatus(Enum):
    """Workspace consent state for data usage."""
    GRANTED = "granted"
    DENIED = "denied"
    UNSPECIFIED = "unspecified"


class ExportPurpose(Enum):
    """Intended use of exported dataset."""
    TRAINING = "training"
    EVALUATION = "evaluation"
    BENCHMARKING = "benchmarking"


@dataclass
class WorkspaceConsent:
    """Consent record for a workspace's data usage."""
    workspace_id: str
    status: ConsentStatus
    granted_purposes: Set[ExportPurpose] = field(default_factory=set)
    updated_at: float = 0.0

    def permits(self, purpose: ExportPurpose) -> bool:
        if self.status == ConsentStatus.DENIED:
            return False
        if self.status == ConsentStatus.UNSPECIFIED:
            return False
        if purpose not in self.granted_purposes:
            return False
        return True


@dataclass
class TaskRecord:
    """A historical task record eligible for dataset export."""
    task_id: str
    workspace_id: str
    agent_id: str
    task_type: str
    payload: Dict[str, Any]
    result: Dict[str, Any]
    created_at: float
    updated_at: float


@dataclass
class ExportManifest:
    """Manifest recorded for each dataset export operation."""
    manifest_id: str
    purpose: ExportPurpose
    consent_criteria: Dict[str, Any]
    selection_time: float
    total_records: int
    included_workspaces: List[str]
    excluded_workspaces: List[str]
    record_ids: List[str]


class DatasetExportPipeline:
    """Dataset export pipeline with consent-gated record selection.

    Selects records from eligible workspaces only, filtering by consent
    status and purpose before inclusion. Produces a manifest documenting
    the selection criteria and outcome.
    """

    def __init__(self):
        self._consent_store: Dict[str, WorkspaceConsent] = {}
        self._records: Dict[str, TaskRecord] = {}
        self._manifests: Dict[str, ExportManifest] = {}
        self._excluded_workspaces: Set[str] = set()

    # --- Workspace consent management ---

    def set_workspace_consent(
        self,
        workspace_id: str,
        status: ConsentStatus,
        purposes: Optional[List[ExportPurpose]] = None,
    ) -> None:
        """Set or update consent for a workspace."""
        existing = self._consent_store.get(workspace_id)
        granted = set(purposes) if purposes else set()
        if existing:
            granted = granted or existing.granted_purposes
        self._consent_store[workspace_id] = WorkspaceConsent(
            workspace_id=workspace_id,
            status=status,
            granted_purposes=granted,
            updated_at=time.time(),
        )

    def get_workspace_consent(self, workspace_id: str) -> Optional[WorkspaceConsent]:
        return self._consent_store.get(workspace_id)

    def revoke_workspace_consent(self, workspace_id: str) -> None:
        """Revoke all consent for a workspace."""
        if workspace_id in self._consent_store:
            self._consent_store[workspace_id] = WorkspaceConsent(
                workspace_id=workspace_id,
                status=ConsentStatus.DENIED,
                updated_at=time.time(),
            )

    # --- Record management ---

    def add_record(self, record: TaskRecord) -> None:
        """Add a task record to the pool."""
        self._records[record.task_id] = record

    def get_record(self, task_id: str) -> Optional[TaskRecord]:
        return self._records.get(task_id)

    def remove_record(self, task_id: str) -> bool:
        return self._records.pop(task_id, None) is not None

    # --- Consent-gated selection ---

    def select_records(self, purpose: ExportPurpose) -> List[TaskRecord]:
        """Select records from workspaces that consent to the given purpose."""
        selected: List[TaskRecord] = []
        for record in self._records.values():
            consent = self._consent_store.get(record.workspace_id)
            if consent and consent.permits(purpose):
                selected.append(record)
        return selected

    def export(self, purpose: ExportPurpose) -> ExportManifest:
        """Run a consent-gated dataset export.

        Selects records, records the manifest, and returns the result.
        Workspaces without consent or with consent denied/unspecified
        are excluded from the export set.
        """
        included_workspaces: Set[str] = set()
        excluded_workspaces: Set[str] = set()

        # Check all workspace consent states
        for record in self._records.values():
            consent = self._consent_store.get(record.workspace_id)
            if consent and consent.permits(purpose):
                included_workspaces.add(record.workspace_id)
            else:
                excluded_workspaces.add(record.workspace_id)

        selected = self.select_records(purpose)

        manifest = ExportManifest(
            manifest_id=str(uuid4()),
            purpose=purpose,
            consent_criteria={
                "purpose": purpose.value,
                "required_consent": ConsentStatus.GRANTED.value,
                "consent_check_time": time.time(),
            },
            selection_time=time.time(),
            total_records=len(selected),
            included_workspaces=sorted(included_workspaces),
            excluded_workspaces=sorted(excluded_workspaces),
            record_ids=[r.task_id for r in selected],
        )

        self._manifests[manifest.manifest_id] = manifest
        return manifest

    def get_manifest(self, manifest_id: str) -> Optional[ExportManifest]:
        return self._manifests.get(manifest_id)

    def list_manifests(self) -> List[ExportManifest]:
        return list(self._manifests.values())
