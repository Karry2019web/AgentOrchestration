"""Storage lifecycle management — artifact storage class and lifecycle reporting."""

import time
from typing import Dict, List, Optional
from threading import Lock


STORAGE_CLASSES = {
    "standard": {"retrieval_ms": 5, "cost_per_gb": 0.023},
    "infrequent_access": {"retrieval_ms": 50, "cost_per_gb": 0.0125},
    "archive": {"retrieval_ms": 300_000, "cost_per_gb": 0.001},
    "deep_archive": {"retrieval_ms": 432_000_000, "cost_per_gb": 0.00099},
}

COLD_STORAGE = {"archive", "deep_archive"}


class StorageLifecycleManager:
    """Tracks artifact storage class transitions and reports lifecycle status."""

    def __init__(self):
        self._lock = Lock()
        self._artifacts: Dict[str, Dict] = {}

    def register_artifact(self, artifact_id: str, storage_class: str = "standard",
                          size_bytes: int = 0) -> None:
        if storage_class not in STORAGE_CLASSES:
            raise ValueError(
                f"Unknown storage class '{storage_class}'. "
                f"Valid classes: {', '.join(STORAGE_CLASSES.keys())}"
            )
        with self._lock:
            self._artifacts[artifact_id] = {
                "artifact_id": artifact_id,
                "current_storage_class": storage_class,
                "original_storage_class": storage_class,
                "size_bytes": size_bytes,
                "lifecycle_transitions": [],
                "created_at": time.time(),
                "last_modified": time.time(),
            }

    def record_transition(self, artifact_id: str, new_storage_class: str,
                          reason: str = "lifecycle_rule") -> bool:
        if new_storage_class not in STORAGE_CLASSES:
            raise ValueError(f"Unknown storage class '{new_storage_class}'")
        with self._lock:
            if artifact_id not in self._artifacts:
                return False
            art = self._artifacts[artifact_id]
            old_class = art["current_storage_class"]
            art["lifecycle_transitions"].append({
                "from_class": old_class,
                "to_class": new_storage_class,
                "timestamp": time.time(),
                "reason": reason,
            })
            art["current_storage_class"] = new_storage_class
            art["last_modified"] = time.time()
            return True

    def get_artifact_report(self, artifact_id: str) -> Optional[Dict]:
        with self._lock:
            art = self._artifacts.get(artifact_id)
            if not art:
                return None
            result = dict(art)
            storage_info = STORAGE_CLASSES.get(art["current_storage_class"], {})
            result["retrieval_estimate_ms"] = storage_info.get("retrieval_ms", 0)
            result["is_cold_storage"] = art["current_storage_class"] in COLD_STORAGE
            result["transition_count"] = len(art["lifecycle_transitions"])
            return result

    def get_all_reports(self) -> List[Dict]:
        with self._lock:
            return [self.get_artifact_report(aid) for aid in self._artifacts]

    def list_cold_storage_artifacts(self) -> List[Dict]:
        with self._lock:
            return [
                self.get_artifact_report(aid)
                for aid, art in self._artifacts.items()
                if art["current_storage_class"] in COLD_STORAGE
            ]


storage_lifecycle = StorageLifecycleManager()
