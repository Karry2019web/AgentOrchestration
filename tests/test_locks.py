"""Tests for the Lock Manager module."""

import pytest
from unittest.mock import MagicMock, patch
from src.common.locks import (
    LockManager,
    DummyLockManager,
    LockState,
    LockTimeoutError,
    LockAcquisitionError,
    _AdvisoryLock,
)


class TestAdvisoryLock:
    def test_acquire_success(self):
        """Test successful lock acquisition."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = [True]
        conn.cursor.return_value = cursor
        lock = _AdvisoryLock(42, conn, key="test-resource", timeout=5.0)
        assert lock.acquire() is True
        assert lock.state == LockState.LOCKED
        assert lock.is_acquired is True
        cursor.execute.assert_called_once_with(
            "SELECT pg_try_advisory_lock(%s)", (42,)
        )

    def test_acquire_already_locked(self):
        """Test acquire on already-locked lock is idempotent."""
        conn = MagicMock()
        lock = _AdvisoryLock(42, conn, key="test", timeout=5.0)
        lock.state = LockState.LOCKED
        assert lock.acquire() is True
        # Should not call the DB again
        conn.cursor.assert_not_called()

    def test_release_success(self):
        """Test successful lock release."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = [True]
        conn.cursor.return_value = cursor
        lock = _AdvisoryLock(42, conn, key="test", timeout=5.0)
        lock.state = LockState.LOCKED
        assert lock.release() is True
        assert lock.state == LockState.RELEASED
        cursor.execute.assert_called_once_with(
            "SELECT pg_advisory_unlock(%s)", (42,)
        )

    def test_release_unlocked_is_noop(self):
        """Test releasing an already-unlocked lock is a no-op."""
        conn = MagicMock()
        lock = _AdvisoryLock(42, conn, key="test", timeout=5.0)
        assert lock.release() is True
        conn.cursor.assert_not_called()

    def test_release_not_held_by_session(self):
        """Test release when lock is not held by this session."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = [False]  # not held by session
        conn.cursor.return_value = cursor
        lock = _AdvisoryLock(42, conn, key="test", timeout=5.0)
        lock.state = LockState.LOCKED
        assert lock.release() is True
        assert lock.state == LockState.RELEASED

    def test_force_release_suppresses_errors(self):
        """Test force_release suppresses exceptions."""
        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError("DB gone")
        lock = _AdvisoryLock(42, conn, key="test", timeout=5.0)
        lock.state = LockState.LOCKED
        # Should not raise
        lock.force_release()
        assert lock.state == LockState.RELEASED

    def test_acquire_timeout(self):
        """Test acquire raises LockTimeoutError when lock is busy."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = [False]  # always busy
        conn.cursor.return_value = cursor
        lock = _AdvisoryLock(42, conn, key="test", timeout=0.1)
        with pytest.raises(LockTimeoutError):
            lock.acquire()
        assert lock.state == LockState.FAILED

    def test_acquire_db_error(self):
        """Test acquire raises LockAcquisitionError on DB failure."""
        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError("Connection lost")
        lock = _AdvisoryLock(42, conn, key="test", timeout=0.1)
        with pytest.raises(LockAcquisitionError):
            lock.acquire()
        assert lock.state == LockState.FAILED


class TestLockManager:
    def setup_method(self):
        self.conn_factory = MagicMock(return_value=MagicMock())
        self.manager = LockManager(self.conn_factory, default_timeout=10.0)

    def test_derive_lock_id(self):
        """Test lock ID derivation is deterministic and positive."""
        id1 = LockManager._derive_lock_id("agent:run:42")
        id2 = LockManager._derive_lock_id("agent:run:42")
        assert id1 == id2
        assert id1 > 0
        assert id1 < 2 ** 31

    def test_derive_lock_id_different_keys(self):
        """Test different keys produce different lock IDs."""
        id1 = LockManager._derive_lock_id("agent:run:42")
        id2 = LockManager._derive_lock_id("agent:run:99")
        assert id1 != id2

    def test_lock_context_manager_success(self):
        """Test lock context manager acquires and releases."""
        cursor = MagicMock()
        cursor.fetchone.return_value = [True]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        factory = MagicMock(return_value=conn)
        manager = LockManager(factory, default_timeout=10.0)

        import asyncio
        async def run_test():
            async with manager.lock("agent:run:42") as lock:
                assert lock.is_acquired
                assert lock.state == LockState.LOCKED

            # After context exit, lock should be released
            assert lock.state == LockState.RELEASED

        asyncio.run(run_test())
        # Verify release was called
        cursor.execute.assert_any_call("SELECT pg_advisory_unlock(%s)", (42,))

    def test_lock_released_on_exception(self):
        """Test lock is released when an exception occurs inside the context."""
        cursor = MagicMock()
        cursor.fetchone.return_value = [True]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        factory = MagicMock(return_value=conn)
        manager = LockManager(factory, default_timeout=10.0)

        import asyncio
        async def run_test():
            with pytest.raises(RuntimeError, match="task failed"):
                async with manager.lock("agent:run:42") as lock:
                    assert lock.is_acquired
                    raise RuntimeError("task failed")

            # Lock should be released despite the exception
            assert lock.state == LockState.RELEASED

        asyncio.run(run_test())

    def test_active_lock_count(self):
        """Test active_lock_count tracks held locks."""
        cursor = MagicMock()
        cursor.fetchone.return_value = [True]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        factory = MagicMock(return_value=conn)
        manager = LockManager(factory, default_timeout=10.0)

        import asyncio
        async def run_test():
            assert manager.active_lock_count() == 0
            async with manager.lock("resource:1"):
                assert manager.active_lock_count() == 1
            assert manager.active_lock_count() == 0

        asyncio.run(run_test())

    def test_is_locked(self):
        """Test is_locked returns correct state."""
        cursor = MagicMock()
        cursor.fetchone.return_value = [True]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        factory = MagicMock(return_value=conn)
        manager = LockManager(factory, default_timeout=10.0)

        import asyncio
        async def run_test():
            assert manager.is_locked("resource:1") is False
            async with manager.lock("resource:1"):
                assert manager.is_locked("resource:1") is True
            assert manager.is_locked("resource:1") is False

        asyncio.run(run_test())


class TestDummyLockManager:
    def setup_method(self):
        self.manager = DummyLockManager()

    def test_lock_always_acquired(self):
        """Test DummyLockManager always reports lock as acquired."""
        import asyncio
        async def run_test():
            async with self.manager.lock("any-resource") as lock:
                assert lock.is_acquired
                assert lock.state == LockState.LOCKED
        asyncio.run(run_test())

    def test_active_count_zero(self):
        """Test DummyLockManager reports zero active locks."""
        assert self.manager.active_lock_count() == 0

    def test_is_locked_false(self):
        """Test DummyLockManager reports nothing as locked."""
        assert self.manager.is_locked("anything") is False
