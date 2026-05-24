"""Tests for LockManager — covering normal acquire/release, exception safety, and retry."""

import time
import threading
import pytest

from src.common.errors import LockAcquisitionError
from src.common.locks import LockManager, get_lock_manager, advisory_lock


class TestLockManager:
    def test_acquire_and_release(self):
        manager = LockManager()
        with manager.acquire("test-key") as lock_id:
            assert lock_id is not None
            assert isinstance(lock_id, int)
        assert manager.held_lock_count == 0

    def test_concurrent_lock_blocks(self):
        manager = LockManager(lock_timeout=1.0, retry_interval=0.1, max_retries=3)
        with manager.acquire("shared-key") as lock_id:
            assert lock_id is not None
            with pytest.raises(LockAcquisitionError):
                with manager.acquire("shared-key", timeout=0.3):
                    pass

    def test_release_on_exception(self):
        manager = LockManager()
        try:
            with manager.acquire("crash-key") as lock_id:
                assert lock_id is not None
                raise ValueError("inside lock")
        except ValueError:
            pass
        assert manager.held_lock_count == 0

    def test_release_on_nested_exception(self):
        manager = LockManager()
        try:
            with manager.acquire("outer"):
                with manager.acquire("inner"):
                    raise RuntimeError("nested crash")
        except RuntimeError:
            pass
        assert manager.held_lock_count == 0

    def test_advisory_lock_id_deterministic(self):
        manager = LockManager()
        id1 = manager._advisory_lock_id("same-key")
        id2 = manager._advisory_lock_id("same-key")
        assert id1 == id2

    def test_different_keys_different_ids(self):
        manager = LockManager()
        id1 = manager._advisory_lock_id("key-a")
        id2 = manager._advisory_lock_id("key-b")
        assert id1 != id2

    def test_release_all(self):
        manager = LockManager()
        with manager.acquire("lock-1"):
            with manager.acquire("lock-2"):
                assert manager.held_lock_count == 2
            assert manager.held_lock_count == 1
        assert manager.held_lock_count == 0

    def test_convenience_function(self):
        with advisory_lock("convenience-key") as lock_id:
            assert lock_id is not None

    def test_retry_eventually_succeeds(self):
        manager = LockManager(lock_timeout=5.0, retry_interval=0.05, max_retries=10)
        result = []

        def hold_then_release():
            with manager.acquire("retry-key"):
                time.sleep(0.2)
            result.append(True)

        t = threading.Thread(target=hold_then_release)
        t.start()
        time.sleep(0.05)

        with manager.acquire("retry-key") as lock_id:
            assert lock_id is not None

        t.join()
        assert result[0] is True
