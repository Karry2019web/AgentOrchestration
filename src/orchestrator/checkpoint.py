"""Checkpoint Store — Deterministic, idempotent checkpoint persistence for resumable workers."""

import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CheckpointKey:
    """Deterministic checkpoint key derived from task, step, and attempt."""

    def __init__(self, task_id: str, step: str, attempt: int):
        self.task_id = task_id
        self.step = step
        self.attempt = attempt

    @property
    def key(self) -> str:
        raw = f"{self.task_id}:{self.step}:{self.attempt}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def composite_key(self) -> str:
        return f"cp:{self.task_id}:{self.step}:{self.attempt}"

    def __repr__(self) -> str:
        return f"CheckpointKey(task_id={self.task_id}, step={self.step}, attempt={self.attempt})"


class CheckpointMetadata:
    """Metadata attached to each checkpoint record."""

    def __init__(
        self,
        key: CheckpointKey,
        content_digest: str,
        data: Dict[str, Any],
        timestamp: float,
    ):
        self.key = key
        self.content_digest = content_digest
        self.data = data
        self.timestamp = timestamp

    def serialize(self) -> Dict[str, Any]:
        return {
            "composite_key": self.key.composite_key,
            "content_digest": self.content_digest,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    @classmethod
    def deserialize(cls, raw: Dict[str, Any]) -> "CheckpointMetadata":
        return cls(
            key=CheckpointKey(
                task_id=raw.get("task_id", ""),
                step=raw.get("step", ""),
                attempt=raw.get("attempt", 0),
            ),
            content_digest=raw.get("content_digest", ""),
            data=raw.get("data", {}),
            timestamp=raw.get("timestamp", 0.0),
        )


class CheckpointStore:
    """Thread-safe in-memory checkpoint store with deterministic keys and upsert semantics."""

    def __init__(self):
        self._store: Dict[str, Tuple[CheckpointMetadata, int]] = {}
        self._task_index: Dict[str, Dict[str, int]] = {}

    def _compute_content_digest(self, data: Dict[str, Any]) -> str:
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def write(self, task_id: str, step: str, attempt: int, data: Dict[str, Any]) -> CheckpointKey:
        """Write a checkpoint with deterministic key. Idempotent — retries produce one record."""
        ck = CheckpointKey(task_id, step, attempt)
        content_digest = self._compute_content_digest(data)
        store_key = ck.key

        if store_key in self._store:
            existing_meta, existing_version = self._store[store_key]
            if existing_meta.content_digest != content_digest:
                raise ValueError(
                    f"Checkpoint digest mismatch for key {ck.composite_key}: "
                    f"existing={existing_meta.content_digest[:16]}, "
                    f"new={content_digest[:16]}."
                )
            existing_meta.timestamp = time.time()
            self._store[store_key] = (existing_meta, existing_version + 1)
            logger.debug(f"Idempotent update for {ck.composite_key} (version {existing_version + 1})")
            return ck

        meta = CheckpointMetadata(ck, content_digest, data, time.time())
        self._store[store_key] = (meta, 1)

        if task_id not in self._task_index:
            self._task_index[task_id] = {}
        self._task_index[task_id][ck.composite_key] = 1

        logger.info(f"Checkpoint written: {ck.composite_key}")
        return ck

    def read(self, task_id: str, step: str, attempt: int) -> Optional[Dict[str, Any]]:
        ck = CheckpointKey(task_id, step, attempt)
        entry = self._store.get(ck.key)
        if entry is None:
            return None
        meta, version = entry
        return {
            "data": meta.data,
            "version": version,
            "timestamp": meta.timestamp,
            "content_digest": meta.content_digest,
        }

    def resume(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest checkpoint for a task (for resume after timeout/retry)."""
        task_checkpoints = self._task_index.get(task_id)
        if not task_checkpoints:
            return None

        best_meta = None
        best_version = 0
        for composite_key, version in task_checkpoints.items():
            store_key = hashlib.sha256(composite_key.encode()).hexdigest()
            entry = self._store.get(store_key)
            if entry is None:
                continue
            meta, _ = entry
            if best_meta is None or meta.key.attempt > best_meta.key.attempt:
                best_meta = meta
                best_version = version

        if best_meta is None:
            return None

        return {
            "data": best_meta.data,
            "version": best_version,
            "timestamp": best_meta.timestamp,
            "content_digest": best_meta.content_digest,
            "key": {
                "task_id": best_meta.key.task_id,
                "step": best_meta.key.step,
                "attempt": best_meta.key.attempt,
            },
        }

    def exists(self, task_id: str, step: str, attempt: int) -> bool:
        ck = CheckpointKey(task_id, step, attempt)
        return ck.key in self._store

    def count(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()
        self._task_index.clear()
