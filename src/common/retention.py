"""Data Retention Manager — Cascading deletion for derived embeddings and indexes."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data store identifiers
# ---------------------------------------------------------------------------

class DataClass(Enum):
    """All recognised data classes in the system."""
    TASK_ARTIFACT = "task_artifact"
    EXECUTION_LOG = "execution_log"
    WORKFLOW_STATE = "workflow_state"
    DERIVED_EMBEDDING = "derived_embedding"
    DERIVED_INDEX = "derived_index"


CASCADE_MAP: Dict[DataClass, Set[DataClass]] = {
    DataClass.TASK_ARTIFACT: {DataClass.DERIVED_EMBEDDING, DataClass.DERIVED_INDEX},
    DataClass.EXECUTION_LOG: {DataClass.DERIVED_INDEX},
    DataClass.WORKFLOW_STATE: {DataClass.DERIVED_EMBEDDING, DataClass.DERIVED_INDEX},
    DataClass.DERIVED_EMBEDDING: set(),
    DataClass.DERIVED_INDEX: set(),
}

# ---------------------------------------------------------------------------
# Deletion manifest
# ---------------------------------------------------------------------------

@dataclass
class DeletionEntry:
    """A single store-level deletion record."""
    store: DataClass
    removed_count: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


@dataclass
class DeletionManifest:
    """Immutable record of a cascade deletion operation."""
    operation_id: str = field(default_factory=lambda: str(uuid4()))
    entries: Dict[DataClass, DeletionEntry] = field(default_factory=dict)
    manifest_created_at: float = field(default_factory=lambda: __import__("time").time())

    def add_entry(self, entry: DeletionEntry) -> None:
        self.entries[entry.store] = entry

    @property
    def all_successful(self) -> bool:
        return all(e.success for e in self.entries.values())

    @property
    def affected_classes(self) -> List[DataClass]:
        return list(self.entries.keys())

    @property
    def total_removed(self) -> int:
        return sum(e.removed_count for e in self.entries.values())

    def summary(self) -> str:
        parts = []
        for dc, entry in self.entries.items():
            status = "OK" if entry.success else f"ERR({'; '.join(entry.errors)})"
            parts.append(f"{dc.value}={entry.removed_count}[{status}]")
        return f"Manifest {self.operation_id[:8]} | {' '.join(parts)}"


# ---------------------------------------------------------------------------
# Store abstraction
# ---------------------------------------------------------------------------

class DataStore:
    """Minimal abstraction over a single data-class store."""

    def __init__(self, data_class: DataClass):
        self.data_class = data_class
        self._records: Dict[str, object] = {}

    def delete_by_owner(self, owner_id: str) -> int:
        """Remove all records owned by *owner_id*. Returns count."""
        before = len(self._records)
        self._records = {k: v for k, v in self._records.items()
                         if not k.startswith(f"{owner_id}:")}
        return before - len(self._records)

    def size(self) -> int:
        return len(self._records)

    def keys(self) -> List[str]:
        return list(self._records.keys())

    def load(self, records: Dict[str, object]) -> None:
        self._records = dict(records)


class StoreRegistry:
    """Registry of all known data stores."""

    def __init__(self):
        self._stores: Dict[DataClass, DataStore] = {}
        for dc in DataClass:
            self._stores[dc] = DataStore(dc)

    def get(self, dc: DataClass) -> DataStore:
        return self._stores[dc]

    def all_stores(self) -> List[DataStore]:
        return list(self._stores.values())


# ---------------------------------------------------------------------------
# Data retention manager
# ---------------------------------------------------------------------------

class DataRetentionManager:
    """Coordinates cascade deletion across primary and derived stores."""

    def __init__(self, registry: Optional[StoreRegistry] = None):
        self.registry = registry or StoreRegistry()

    def delete_owner_data(self, owner_id: str,
                          primary_classes: Optional[List[DataClass]] = None) -> DeletionManifest:
        """Delete *owner_id* data from *primary_classes* and cascade to derived stores.

        When *primary_classes* is ``None`` (default), every DataClass is treated
        as a primary store so all data for the owner is removed.
        """
        manifest = DeletionManifest()

        if primary_classes is None:
            primary_classes = [dc for dc in DataClass]

        # Phase 1 — collect affected derived classes before mutating anything
        affected_derived: Set[DataClass] = set()
        for primary_dc in primary_classes:
            affected_derived.update(CASCADE_MAP.get(primary_dc, set()))

        all_targets = set(primary_classes) | affected_derived

        # Phase 2 — delete from each target store
        for dc in sorted(all_targets, key=lambda x: x.value):
            store = self.registry.get(dc)
            try:
                removed = store.delete_by_owner(owner_id)
                manifest.add_entry(DeletionEntry(store=dc, removed_count=removed))
                logger.info("Deleted %d records from %s for owner %s",
                            removed, dc.value, owner_id)
            except Exception as exc:
                logger.error("Failed to delete from %s for owner %s: %s",
                             dc.value, owner_id, exc)
                manifest.add_entry(DeletionEntry(store=dc, errors=[str(exc)]))

        # Phase 3 — reconcile: detect stale references
        stale_found = self._reconcile(owner_id)
        if stale_found:
            logger.warning("Reconciliation found %d stale derived records for owner %s",
                           stale_found, owner_id)

        return manifest

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile_all(self) -> Dict[str, int]:
        """Walk every store and log orphans. Returns {data_class: stale_count}."""
        results = {}
        for store in self.registry.all_stores():
            stale = self._detect_stale(store)
            if stale:
                results[store.data_class.value] = stale
        return results

    def _reconcile(self, owner_id: str) -> int:
        """Return the number of stale derived records for *owner_id*."""
        stale = 0
        for dc in (DataClass.DERIVED_EMBEDDING, DataClass.DERIVED_INDEX):
            store = self.registry.get(dc)
            for key in store.keys():
                if key.startswith(f"{owner_id}:") and not self._owner_has_primary(key, owner_id):
                    stale += 1
        return stale

    def _detect_stale(self, store: DataStore) -> int:
        stale = 0
        for key in store.keys():
            if store.data_class in (DataClass.DERIVED_EMBEDDING, DataClass.DERIVED_INDEX):
                owner = key.split(":", 1)[0]
                if not self._owner_has_primary(owner, owner):
                    stale += 1
        return stale

    def _owner_has_primary(self, record_key: str, owner_id: str) -> bool:
        derived_dcs = {DataClass.DERIVED_EMBEDDING, DataClass.DERIVED_INDEX}
        for dc in DataClass:
            if dc in derived_dcs:
                continue
            store = self.registry.get(dc)
            if any(k.startswith(f"{owner_id}:") for k in store.keys()):
                return True
        return False
