"""Tests for the Lock Manager module."""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.orchestrator.lock_manager import (
    AdvisoryLock,
    LockManager,
    LockNotAcquiredError,
    LockReleaseError,
)


class TestAdvisoryLock:
    """Tests for the AdvisoryLock class."""

    def test_release_success(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        lock = AdvisoryLock(lock_id=12345, conn=conn)
        assert not lock.is_released

        lock.release()
        assert lock.is_released
        cursor.execute.assert_called_once_with(
            "SELECT pg_advisory_unlock(%s)", (12345,)
        )
        conn.commit.assert_called_once()

    def test_release_idempotent(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        lock = AdvisoryLock(lock_id=12345, conn=conn)
        lock.release()
        lock.release()
        cursor.execute.assert_called_once()

    def test_release_failure_raises(self):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("DB error")
        conn.cursor.return_value.__enter__.return_value = cursor

        lock = AdvisoryLock(lock_id=12345, conn=conn)
        with pytest.raises(LockReleaseError):
            lock.release()

    def test_context_manager_releases_on_exception(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        lock = AdvisoryLock(lock_id=12345, conn=conn)
        try:
            with lock as lk:
                assert lk is lock
                raise ValueError("task error")
        except ValueError:
            pass

        assert lock.is_released
        cursor.execute.assert_called_once()

    def test_context_manager_no_exception(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        with AdvisoryLock(lock_id=12345, conn=conn) as lock:
            assert not lock.is_released

        assert lock.is_released


class TestLockManager:
    """Tests for the LockManager class."""

    def test_compute_lock_id_deterministic(self):
        lm = LockManager()
        id1 = lm._compute_lock_id("resource:alpha", "task:1")
        id2 = lm._compute_lock_id("resource:alpha", "task:1")
        assert id1 == id2

    def test_compute_lock_id_different_keys_differ(self):
        lm = LockManager()
        id1 = lm._compute_lock_id("resource:alpha")
        id2 = lm._compute_lock_id("resource:beta")
        assert id1 != id2

    def test_compute_lock_id_positive(self):
        lm = LockManager()
        lock_id = lm._compute_lock_id("resource:test")
        assert lock_id > 0

    def test_no_dsn_uses_single_connection(self):
        lm = LockManager(dsn="")
        assert lm._pool is None

    def test_initial_state_empty(self):
        lm = LockManager()
        assert lm.active_lock_count == 0
        assert lm.tracked_task_count == 0

    def test_release_all_when_empty(self):
        lm = LockManager()
        count = lm.release_all()
        assert count == 0

    def test_release_unknown_key(self):
        lm = LockManager()
        result = lm.release("nonexistent")
        assert result is False

    def test_release_by_task_unknown(self):
        lm = LockManager()
        result = lm.release_by_task("nonexistent")
        assert result is False

    def test_detect_stale_no_locks(self):
        lm = LockManager()
        count = lm.detect_stale_locks()
        assert count == 0

    def test_context_manager_without_dsn(self):
        lm = LockManager(dsn="")
        with patch.object(lm, "acquire") as mock_acquire:
            mock_lock = MagicMock()
            mock_lock.is_released = False
            mock_acquire.return_value = mock_lock
            with lm.lock("resource:test", task_id="task-1") as lock_obj:
                assert lock_obj is mock_lock
            mock_acquire.assert_called_once_with("resource:test", task_id="task-1")

    def test_context_manager_releases_on_exception(self):
        lm = LockManager(dsn="")
        with patch.object(lm, "acquire") as mock_acquire:
            mock_lock = MagicMock()
            mock_lock.is_released = False
            mock_acquire.return_value = mock_lock
            with patch.object(lm, "release") as mock_release:
                mock_release.return_value = True
                try:
                    with lm.lock("resource:test", task_id="task-1"):
                        raise ValueError("crash")
                except ValueError:
                    pass
                mock_release.assert_called_once_with("resource:test")

    def test_context_manager_no_false_release_if_already_released(self):
        lm = LockManager(dsn="")
        with patch.object(lm, "acquire") as mock_acquire:
            mock_lock = MagicMock()
            mock_lock.is_released = True
            mock_acquire.return_value = mock_lock
            with patch.object(lm, "release") as mock_release:
                with lm.lock("resource:test"):
                    pass
                mock_release.assert_not_called()

    def test_lock_manager_close_cleanup(self):
        lm = LockManager(dsn="")
        with patch.object(lm, "release_all") as mock_release:
            lm.close()
            mock_release.assert_called_once()

    def test_lock_manager_properties(self):
        lm = LockManager()
        assert lm.active_lock_count == 0
        assert lm.tracked_task_count == 0
        assert lm.release_all() == 0


class TestLockManagerIntegration:
    """Integration-style tests with mocked psycopg2."""

    @patch("src.orchestrator.lock_manager.psycopg2")
    def test_acquire_lock_success(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [True]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        lm = LockManager(dsn="dbname=test")
        lock = lm.acquire("resource:alpha", task_id="task-1")

        assert lock.lock_id > 0
        assert not lock.is_released
        assert lm.active_lock_count == 1
        assert lm.tracked_task_count == 1
        lock.release()

    @patch("src.orchestrator.lock_manager.psycopg2")
    def test_acquire_lock_retry_then_success(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [[False], [True]]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        lm = LockManager(dsn="dbname=test", max_retries=3, retry_interval=0.01)
        lock = lm.acquire("resource:beta")
        assert not lock.is_released
        assert mock_cursor.fetchone.call_count == 2

    @patch("src.orchestrator.lock_manager.psycopg2")
    def test_acquire_lock_exhausts_retries(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [False]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        lm = LockManager(dsn="dbname=test", max_retries=2, retry_interval=0.01)
        with pytest.raises(LockNotAcquiredError):
            lm.acquire("resource:gamma")

    @patch("src.orchestrator.lock_manager.psycopg2")
    def test_acquire_and_release_by_key(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [True]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        lm = LockManager(dsn="dbname=test")
        lm.acquire("resource:delta", task_id="task-2")
        assert lm.active_lock_count == 1

        result = lm.release("resource:delta")
        assert result is True
        assert lm.active_lock_count == 0

    @patch("src.orchestrator.lock_manager.psycopg2")
    def test_release_by_task(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [True]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        lm = LockManager(dsn="dbname=test")
        lm.acquire("resource:epsilon", task_id="task-3")
        assert lm.tracked_task_count == 1

        result = lm.release_by_task("task-3")
        assert result is True
        assert lm.tracked_task_count == 0

    @patch("src.orchestrator.lock_manager.psycopg2")
    def test_acquire_failure_raises_and_rolls_back(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("Connection lost")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        lm = LockManager(dsn="dbname=test", max_retries=1, retry_interval=0.01)
        with pytest.raises(LockNotAcquiredError):
            lm.acquire("resource:zeta")
        assert mock_conn.rollback.called

    @patch("src.orchestrator.lock_manager.psycopg2")
    def test_detect_stale_locks(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [True]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        lm = LockManager(dsn="dbname=test", stale_threshold=0)
        lm.acquire("resource:theta", task_id="task-4")
        lm.acquire("resource:iota", task_id="task-5")
        
        with patch.object(lm, "_active_locks") as mock_active:
            mock_active.items.return_value = []
            count = lm.detect_stale_locks()
            assert count == 0

    @patch("src.orchestrator.lock_manager.psycopg2")
    def test_release_all_clears_task_locks(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [True]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        lm = LockManager(dsn="dbname=test")
        lm.acquire("resource:kappa", task_id="task-6")
        assert lm.active_lock_count == 1
        assert lm.tracked_task_count == 1

        lm.release_all()
        assert lm.active_lock_count == 0
        assert lm.tracked_task_count == 0
