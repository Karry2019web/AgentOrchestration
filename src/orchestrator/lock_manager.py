"""Lock Manager — PostgreSQL advisory lock management for orchestration tasks.

Ensures database advisory locks are always released, even on exception paths.
Uses try/finally and context managers to guarantee locks are not leaked.
"""

import logging
import time
from contextlib import contextmanager
from typing import Dict, Generator, Optional

import psycopg2
import psycopg2.extensions
import psycopg2.pool

logger = logging.getLogger(__name__)


class LockNotAcquiredError(Exception):
    """Raised when a lock cannot be acquired."""
    pass


class LockReleaseError(Exception):
    """Raised when a lock fails to release properly."""
    pass


class AdvisoryLock:
    """Represents an acquired PostgreSQL advisory lock.

    Uses session-level advisory locks (pg_try_advisory_xact_lock)
    so they auto-release on transaction end, with explicit release
    as defense-in-depth via __exit__.
    """

    def __init__(self, lock_id: int, conn: psycopg2.extensions.connection):
        self.lock_id = lock_id
        self.conn = conn
        self.acquired_at: float = time.time()
        self._released = False

    def release(self) -> None:
        """Explicitly release the advisory lock."""
        if self._released:
            return
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (self.lock_id,))
            self.conn.commit()
            self._released = True
            logger.debug("Released advisory lock %s", self.lock_id)
        except Exception as e:
            logger.error("Failed to release advisory lock %s: %s", self.lock_id, e)
            raise LockReleaseError(f"Failed to release lock {self.lock_id}: {e}") from e

    @property
    def is_released(self) -> bool:
        return self._released

    def __enter__(self) -> "AdvisoryLock":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Always release the lock on context exit, regardless of exception."""
        if not self._released:
            self.release()


class LockManager:
    """Manages PostgreSQL advisory locks for distributed orchestration.

    Features:
    - Configurable lock timeout and retry
    - Automatic release on exception via context managers
    - Stale lock detection
    - Connection pool management
    """

    def __init__(
        self,
        dsn: str = "",
        pool_min: int = 1,
        pool_max: int = 10,
        retry_interval: float = 0.5,
        max_retries: int = 3,
        stale_threshold: float = 300.0,
        auto_reconnect: bool = True,
    ):
        self.dsn = dsn
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.stale_threshold = stale_threshold
        self.auto_reconnect = auto_reconnect
        self._pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
        if dsn:
            self._init_pool(pool_min, pool_max)
        self._active_locks: Dict[int, AdvisoryLock] = {}
        self._task_locks: Dict[str, int] = {}

    def _init_pool(self, minconn: int, maxconn: int) -> None:
        try:
            self._pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, self.dsn)
            logger.info("Connection pool initialized (min=%d, max=%d)", minconn, maxconn)
        except Exception as e:
            logger.warning("Failed to initialize connection pool: %s", e)
            self._pool = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._pool:
            try:
                return self._pool.getconn()
            except Exception as e:
                if self.auto_reconnect:
                    logger.warning("Pool exhausted, creating temp connection: %s", e)
                    return psycopg2.connect(self.dsn)
                raise
        return psycopg2.connect(self.dsn)

    def _put_conn(self, conn: psycopg2.extensions.connection) -> None:
        if self._pool:
            try:
                self._pool.putconn(conn)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
        else:
            try:
                conn.close()
            except Exception:
                pass

    def _compute_lock_id(self, *parts: str) -> int:
        combined = ":".join(str(p) for p in parts)
        return hash(combined) & 0x7FFFFFFFFFFFFFFF

    def _check_conn_alive(self, conn: psycopg2.extensions.connection) -> bool:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception:
            return False

    def acquire(self, lock_key: str, task_id: Optional[str] = None) -> AdvisoryLock:
        """Acquire a PostgreSQL advisory lock with retry logic.

        Args:
            lock_key: A string key identifying the resource to lock.
            task_id: Optional task identifier for tracking.

        Returns:
            An AdvisoryLock instance.

        Raises:
            LockNotAcquiredError: If the lock cannot be acquired within retry limits.
        """
        lock_id = self._compute_lock_id(lock_key)
        conn = self._get_conn()

        if not self._check_conn_alive(conn):
            if self.auto_reconnect:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = psycopg2.connect(self.dsn)
            else:
                raise LockNotAcquiredError(f"Connection not alive for lock {lock_key}")

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_id,))
                    acquired = cur.fetchone()[0]

                    if acquired:
                        conn.commit()
                        lock = AdvisoryLock(lock_id, conn)
                        self._active_locks[lock_id] = lock
                        if task_id:
                            self._task_locks[task_id] = lock_id
                        logger.info(
                            "Acquired advisory lock %d for key '%s' (attempt %d/%d)",
                            lock_id, lock_key, attempt + 1, self.max_retries + 1,
                        )
                        return lock

                    conn.rollback()
                    if attempt < self.max_retries:
                        logger.debug(
                            "Lock %d busy for key '%s', retrying in %.1fs",
                            lock_id, lock_key, self.retry_interval,
                        )
                        time.sleep(self.retry_interval)
                    else:
                        raise LockNotAcquiredError(
                            f"Could not acquire advisory lock {lock_id} for key '{lock_key}' "
                            f"after {self.max_retries + 1} attempts"
                        )

            except LockNotAcquiredError:
                raise
            except Exception as e:
                last_error = e
                conn.rollback()
                if attempt < self.max_retries:
                    time.sleep(self.retry_interval)
                    if not self._check_conn_alive(conn):
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = psycopg2.connect(self.dsn)
                else:
                    raise LockNotAcquiredError(
                        f"Failed to acquire lock '{lock_key}' after {self.max_retries + 1} attempts: {last_error}"
                    ) from last_error

        raise LockNotAcquiredError(f"Failed to acquire lock '{lock_key}'")

    def release(self, lock_key: str) -> bool:
        """Release an advisory lock by key."""
        lock_id = self._compute_lock_id(lock_key)
        lock = self._active_locks.pop(lock_id, None)
        if lock is None:
            logger.warning("Attempted to release unknown lock for key '%s'", lock_key)
            return False

        for tid, lid in list(self._task_locks.items()):
            if lid == lock_id:
                del self._task_locks[tid]

        try:
            lock.release()
            self._put_conn(lock.conn)
            return True
        except LockReleaseError:
            raise
        except Exception as e:
            logger.error("Error releasing lock for key '%s': %s", lock_key, e)
            return False

    def release_by_task(self, task_id: str) -> bool:
        """Release the advisory lock held by a specific task."""
        lock_id = self._task_locks.pop(task_id, None)
        if lock_id is None:
            return False
        lock = self._active_locks.pop(lock_id, None)
        if lock is None:
            return False
        try:
            lock.release()
            self._put_conn(lock.conn)
            return True
        except Exception as e:
            logger.error("Error releasing lock for task %s: %s", task_id, e)
            return False

    @contextmanager
    def lock(self, lock_key: str, task_id: Optional[str] = None) -> Generator[AdvisoryLock, None, None]:
        """Context manager for safe lock acquisition and automatic release.

        Ensures the lock is always released, even if the enclosed code raises an exception.

        Usage:
            with lock_manager.lock("resource:123", task_id="task-abc") as lk:
                # critical section
                ...
            # lock is released here, even if exception occurred
        """
        lock_obj = None
        try:
            lock_obj = self.acquire(lock_key, task_id=task_id)
            yield lock_obj
        finally:
            if lock_obj is not None and not lock_obj.is_released:
                try:
                    self.release(lock_key)
                except Exception as e:
                    logger.error("Failed to release lock '%s' in context cleanup: %s", lock_key, e)

    def release_all(self) -> int:
        """Release all currently held locks. Returns count of locks released."""
        count = 0
        for lock_id, lock in list(self._active_locks.items()):
            try:
                lock.release()
                self._put_conn(lock.conn)
                count += 1
            except Exception as e:
                logger.error("Failed to release lock %d during release_all: %s", lock_id, e)
        self._active_locks.clear()
        self._task_locks.clear()
        return count

    def detect_stale_locks(self) -> int:
        """Detect and clean up locks held longer than stale_threshold. Returns count removed."""
        now = time.time()
        stale_ids = [
            lock_id
            for lock_id, lock in list(self._active_locks.items())
            if (now - lock.acquired_at) > self.stale_threshold
        ]
        for lock_id in stale_ids:
            lock = self._active_locks.pop(lock_id, None)
            if lock:
                logger.warning("Releasing stale lock %d (held for %.1fs)", lock_id, now - lock.acquired_at)
                try:
                    lock.release()
                    self._put_conn(lock.conn)
                except Exception as e:
                    logger.error("Failed to release stale lock %d: %s", lock_id, e)

        for tid, lid in list(self._task_locks.items()):
            if lid in stale_ids:
                del self._task_locks[tid]

        return len(stale_ids)

    def close(self) -> None:
        """Release all locks and close the connection pool."""
        self.release_all()
        if self._pool:
            self._pool.closeall()
            self._pool = None
            logger.info("Connection pool closed")

    @property
    def active_lock_count(self) -> int:
        return len(self._active_locks)

    @property
    def tracked_task_count(self) -> int:
        return len(self._task_locks)
