"""Retention and cascade deletion — deletion manifest and store lifecycle."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


@dataclass
class DeletionManifest:
    """Tracks deletion across primary and derived data stores."""

    artifact_id: str
    data_class: str
    primary_stores: List[str] = field(default_factory=list)
    derived_stores: List[str] = field(default_factory=list)
    completed_stores: Dict[str, datetime] = field(default_factory=dict)
    failed_stores: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        self.id = str(uuid4())
        self.completed_stores = dict(self.completed_stores or {})
        self.failed_stores = dict(self.failed_stores or {})

    @property
    def all_stores(self) -> List[str]:
        return self.primary_stores + self.derived_stores

    @property
    def is_complete(self) -> bool:
        expected = set(self.all_stores)
        completed = set(self.completed_stores.keys())
        failed = set(self.failed_stores.keys())
        return expected == completed and not failed

    def mark_completed(self, store_id: str) -> None:
        if store_id in self.failed_stores:
            del self.failed_stores[store_id]
        self.completed_stores[store_id] = datetime.now(timezone.utc)

    def mark_failed(self, store_id: str, error: str) -> None:
        if store_id in self.completed_stores:
            del self.completed_stores[store_id]
        self.failed_stores[store_id] = error

    def get_summary(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.id,
            "artifact_id": self.artifact_id,
            "data_class": self.data_class,
            "primary_stores": self.primary_stores,
            "derived_stores": self.derived_stores,
            "completed_stores": list(self.completed_stores.keys()),
            "failed_stores": self.failed_stores,
            "all_complete": self.is_complete,
            "timestamp": self.timestamp.isoformat(),
        }


DeletionHandler = Callable[[str, Dict[str, Any]], bool]


class CascadeDeletion:
    """Orchestrates cascade deletion across primary and derived stores."""

    def __init__(self):
        self._handlers: Dict[str, DeletionHandler] = {}
        self._manifest_registry: Dict[str, DeletionManifest] = {}
        self._known_artifacts: Dict[str, List[str]] = {}

    def register_handler(self, store_id: str, handler: DeletionHandler) -> None:
        self._handlers[store_id] = handler

    def create_manifest(
        self,
        artifact_id: str,
        data_class: str,
        primary_stores: Optional[List[str]] = None,
        derived_stores: Optional[List[str]] = None,
    ) -> DeletionManifest:
        all_primary = primary_stores or []
        all_derived = derived_stores or []

        manifest = DeletionManifest(
            artifact_id=artifact_id,
            data_class=data_class,
            primary_stores=[s for s in all_primary if s in self._handlers],
            derived_stores=[s for s in all_derived if s in self._handlers],
        )
        self._manifest_registry[manifest.id] = manifest
        self._known_artifacts.setdefault(artifact_id, []).append(manifest.id)
        return manifest

    def execute(self, manifest: DeletionManifest, context: Dict[str, Any] = None) -> DeletionManifest:
        context = context or {}
        for store_id in manifest.all_stores:
            handler = self._handlers.get(store_id)
            if handler is None:
                manifest.mark_failed(store_id, f"No handler registered for store: {store_id}")
                continue
            try:
                success = handler(store_id, context)
                if success:
                    manifest.mark_completed(store_id)
                else:
                    manifest.mark_failed(store_id, "Handler returned failure")
            except Exception as e:
                manifest.mark_failed(store_id, str(e))
        return manifest

    def cascade_delete(
        self,
        artifact_id: str,
        data_class: str,
        primary_stores: List[str],
        derived_stores: Optional[List[str]] = None,
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        manifest = self.create_manifest(artifact_id, data_class, primary_stores, derived_stores or [])
        self.execute(manifest, context)
        return manifest.get_summary()

    def reconciliation_scan(self) -> List[Dict[str, Any]]:
        stale: List[Dict[str, Any]] = []
        for artifact_id, manifest_ids in self._known_artifacts.items():
            for mid in manifest_ids:
                manifest = self._manifest_registry.get(mid)
                if manifest is None:
                    continue
                for store_id in manifest.all_stores:
                    if store_id not in manifest.completed_stores and store_id not in manifest.failed_stores:
                        stale.append({
                            "artifact_id": artifact_id,
                            "manifest_id": mid,
                            "store_id": store_id,
                            "data_class": manifest.data_class,
                        })
        return stale

    def get_manifest(self, manifest_id: str) -> Optional[DeletionManifest]:
        return self._manifest_registry.get(manifest_id)

    def get_results(self, artifact_id: str) -> List[Dict[str, Any]]:
        manifest_ids = self._known_artifacts.get(artifact_id, [])
        return [self._manifest_registry[mid].get_summary() for mid in manifest_ids if mid in self._manifest_registry]
