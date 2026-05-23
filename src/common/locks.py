"""Lock Manager — Database advisory lock management for distributed orchestration.

Uses PostgreSQL advisory locks to provide distributed mutual exclusion
for orchestration state transitions. Locks are automatically released
on exception via context manager protocol, preventing orphaned locks.
"""

import asyncio
import logging
import time
import functools
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
from typing import Any, Callable, Dict, Optional, AsyncIterator, Iterator
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class LockState(Enum):
    UNLOCKED = "unlocked"
    LOCKED = "locked"
    RELEASED = "released"
    FAILED = "failed"


class LockTimeoutError(Exception):
    pass


class LockAcquisitionError(Exception):
    pass


class LockReleaseError(Exception):
    pass


class _AdvisoryLock:
    def __init__(self, lock_id: int, db_connection, key: str = "", timeout: float = 30.0):
        self.lock_id = lock_id
        self.db_connection = db_connection
        self.key = key
        self.timeout = timeout
        self.state = LockState.UNLOCKED
        self.acquired_at = None
        self._owner_id = ""

    @property
    def is_acquired(self) -> bool:
        return self.state == LockState.LOCKED

    def acquire(self) -> bool:
        if self.state == LockState.LOCKED:
            return True
        deadline = time.monotonic() + self.timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                cursor = self.db_connection.cursor()
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (self.lock_id,))
                acquired = cursor.fetchone()[0]
                cursor.close()
                if acquired:
                    self.state = LockState.LOCKED
                    self.acquired_at = time.time()
                    self._owner_id = str(uuid4())
                    return True
                asyncio.sleep(0.05)
            except Exception as exc:
                last_error = str(exc)
                asyncio.sleep(0.1)
        self.state = LockState.FAILED
        if last_error:
            raise LockAcquisitionError(
                f"Failed to acquire lock {self.lock_id} ({self.key}): {last_error}"
            )
        raise LockTimeoutError(
            f"Timed out after {self.timeout}s waiting for lock "
            f"{self.lock_id} ({self.key})"
        )

    def release(self) -> bool:
        if self.state != LockState.LOCKED:
            return True
        try:
            cursor = self.db_connection.cursor()
            cursor.execute("SELECT pg_advisory_unlock(%s)", (self.lock_id,))
            released = cursor.fetchone()[0]
            cursor.close()
            self.state = LockState.RELEASED
            return True
        except Exception as exc:
            self.state = LockState.FAILED
            raise LockReleaseError(f"Failed to release lock {self.lock_id}: {exc}") from exc

    def force_release(self) -> None:
        try:
            self.release()
        except Exception:
            self.state = LockState.RELEASED


class LockManager:
    def __init__(self, db_connection_factory: Callable, default_timeout: float = 30.0):
        self._db_connection_factory = db_connection_factory
        self._default_timeout = default_timeout
        self._active_locks = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _derive_lock_id(resource_key: str) -> int:
        return abs(hash(resource_key)) % (2 ** 31 - 1)

    @asynccontextmanager
    async def lock(self, resource_key: str, timeout=None):
        lock_id = self._derive_lock_id(resource_key)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        conn = self._db_connection_factory()
        lock_obj = _AdvisoryLock(lock_id, conn, key=resource_key, timeout=effective_timeout)
        async with self._lock:
            self._active_locks[resource_key] = lock_obj
        acquired = False
        try:
            lock_obj.acquire()
            acquired = True
            yield lock_obj
        except (LockTimeoutError, LockAcquisitionError) as exc:
            lock_obj.state = LockState.RELEASED
            yield lock_obj
        except Exception:
            lock_obj.force_release()
            acquired = False
            raise
        finally:
            if acquired:
                try:
                    lock_obj.release()
                except LockReleaseError:
                    lock_obj.force_release()
            async with self._lock:
                self._active_locks.pop(resource_key, None)
            try:
                conn.close()
            except Exception:
                pass

    @contextmanager
    def lock_sync(self, resource_key: str, timeout=None):
        lock_id = self._derive_lock_id(resource_key)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        conn = self._db_connection_factory()
        lock_obj = _AdvisoryLock(lock_id, conn, key=resource_key, timeout=effective_timeout)
        acquired = False
        try:
            lock_obj.acquire()
            acquired = True
            yield lock_obj
        except (LockTimeoutError, LockAcquisitionError) as exc:
            yield lock_obj
        except Exception:
            lock_obj.force_release()
            acquired = False
            raise
        finally:
            if acquired:
                try:
                    lock_obj.release()
                except LockReleaseError:
                    lock_obj.force_release()
            try:
                conn.close()
            except Exception:
                pass

    def active_lock_count(self) -> int:
        return len(self._active_locks)

    def is_locked(self, resource_key: str) -> bool:
        lock = self._active_locks.get(resource_key)
        return lock is not None and lock.is_acquired


class DummyLockManager:
    class _DummyLock:
        is_acquired = True
        state = LockState.LOCKED
        def release(self):
            self.state = LockState.RELEASED
            return True
        def force_release(self):
            self.state = LockState.RELEASED

    def __init__(self):
        self._dummy = self._DummyLock()

    @asynccontextmanager
    async def lock(self, resource_key: str, timeout=None):
        yield self._dummy

    @contextmanager
    def lock_sync(self, resource_key: str, timeout=None):
        yield self._dummy

    def active_lock_count(self) -> int:
        return 0

    def is_locked(self, resource_key: str) -> bool:
        return False
