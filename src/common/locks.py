"""Database Advisory Lock Manager — Exception-safe lock acquisition and release."""

import logging
import time
import uuid
from contextlib import contextmanager
from typing import Dict, Generator, Optional, Set

from src.common.errors import LockAcquisitionError

logger = logging.getLogger(__name__)


class LockManager:
    """Manages database advisory locks with automatic release on exceptions.
    
    Uses a context-manager pattern so locks are always released, even when
    the enclosed code raises an exception. Retries are bounded and idempotent.
    """

    def __init__(self, lock_timeout: float = 30.0, retry_interval: float = 0.5, max_retries: int = 3):
        self._lock_timeout = lock_timeout
        self._retry_interval = retry_interval
        self._max_retries = max_retries
        self._held_locks: Set[int] = set()
        self._lock_owners: Dict[int, str] = {}

    def _advisory_lock_id(self, key: str) -> int:
        """Convert a string key to a deterministic signed 64-bit advisory lock ID."""
        raw = uuid.uuid5(uuid.NAMESPACE_DNS, key).int
        masked = raw & 0x7FFFFFFFFFFFFFFF
        return masked

    @contextmanager
    def acquire(self, key: str, timeout: Optional[float] = None) -> Generator[int, None, None]:
        """Acquire a database advisory lock, releasing automatically on exit.
        
        Args:
            key: A string key to derive the advisory lock ID from.
            timeout: Maximum time to wait for the lock. Defaults to instance lock_timeout.
            
        Yields:
            The advisory lock ID.
            
        Raises:
            LockAcquisitionError: If the lock cannot be acquired within the timeout.
        """
        lock_id = self._advisory_lock_id(key)
        deadline = time.time() + (timeout or self._lock_timeout)
        owner = str(uuid.uuid4())
        acquired = False
        attempt = 0

        try:
            while time.time() < deadline and attempt < self._max_retries:
                attempt += 1
                if self._try_acquire(lock_id, owner):
                    acquired = True
                    break
                if attempt < self._max_retries:
                    logger.debug(
                        "Lock %d busy (attempt %d/%d), retrying in %.1fs",
                        lock_id, attempt, self._max_retries, self._retry_interval,
                    )
                    time.sleep(self._retry_interval)

            if not acquired:
                raise LockAcquisitionError(lock_id, key, timeout or self._lock_timeout)

            self._held_locks.add(lock_id)
            self._lock_owners[lock_id] = owner
            logger.info("Lock %d acquired for key '%s' (owner=%s)", lock_id, key, owner)

            yield lock_id

        except Exception:
            if acquired:
                self._release(lock_id, owner)
                self._held_locks.discard(lock_id)
                self._lock_owners.pop(lock_id, None)
            raise

        else:
            self._release(lock_id, owner)
            self._held_locks.discard(lock_id)
            self._lock_owners.pop(lock_id, None)
            logger.info("Lock %d released for key '%s'", lock_id, key)

    def _try_acquire(self, lock_id: int, owner: str) -> bool:
        """Attempt to acquire an advisory lock."""
        if lock_id in self._held_locks:
            return False
        self._held_locks.add(lock_id)
        self._lock_owners[lock_id] = owner
        return True

    def _release(self, lock_id: int, owner: str) -> None:
        """Release an advisory lock."""
        current_owner = self._lock_owners.get(lock_id)
        if current_owner == owner:
            self._held_locks.discard(lock_id)
            self._lock_owners.pop(lock_id, None)
        elif current_owner is None:
            pass
        else:
            logger.warning(
                "Attempted to release lock %d owned by %s from %s",
                lock_id, current_owner, owner,
            )

    def release_all(self) -> None:
        """Release all held locks. Called during cleanup/shutdown."""
        for lock_id in list(self._held_locks):
            owner = self._lock_owners.get(lock_id)
            if owner:
                self._release(lock_id, owner)
            self._held_locks.discard(lock_id)
        logger.info("Released all %d held locks", len(self._held_locks))

    @property
    def held_lock_count(self) -> int:
        return len(self._held_locks)


_lock_manager: Optional[LockManager] = None


def get_lock_manager() -> LockManager:
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager


@contextmanager
def advisory_lock(key: str, timeout: Optional[float] = None) -> Generator[int, None, None]:
    """Convenience function: acquire a named advisory lock with automatic cleanup."""
    manager = get_lock_manager()
    with manager.acquire(key, timeout) as lock_id:
        yield lock_id
