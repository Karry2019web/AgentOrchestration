"""JSONL Event Logger — Atomic writes, concurrent appender safety, and log rotation.

Provides a thread-safe, process-safe JSONL event log writer with atomic
write semantics and rotation that preserves every complete record.
"""

import json
import os
import fcntl
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


_LOCK_SUFFIX = ".lock"


class EventLogWriter:
    """Thread-safe and process-safe JSONL event log writer.

    Uses atomic write (write to temp file → fsync → rename) and a POSIX
    file lock to serialise concurrent appenders across processes.

    Attributes:
        path: Absolute path to the primary log file.
        max_bytes: Rotate when the log file exceeds this size (0 = never).
        backup_count: Number of rotated backup files to retain.
    """

    def __init__(
        self,
        path: str,
        max_bytes: int = 0,
        backup_count: int = 3,
    ) -> None:
        self.path = Path(path).resolve()
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        self._lock_path = self.path.with_suffix(self.path.suffix + _LOCK_SUFFIX)

        # In-process lock for thread safety
        self._thread_lock = threading.Lock()
        # File descriptor for cross-process lock (opened lazily)
        self._lock_fd: Optional[int] = None

        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, record: Dict[str, Any]) -> None:
        """Atomically append *record* as one JSONL line.

        Safe to call from multiple threads and multiple processes.
        """
        line = json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"

        with self._thread_lock:
            self._acquire_file_lock()

            try:
                self._maybe_rotate()
                self._atomic_append(line)

                # Sync the directory entry for the rename step below
                # (the rename itself is atomic on POSIX; sync the dir
                #  so the new path is durable on disk).
                self._sync_parent()
            finally:
                self._release_file_lock()

    def read_all(self) -> List[Dict[str, Any]]:
        """Return all records written so far (best-effort)."""
        records: List[Dict[str, Any]] = []
        if not self.path.exists():
            return records

        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Skip partial / corrupt lines
                        continue
        return records

    def close(self) -> None:
        """Release the cross-process file lock, if held."""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def __enter__(self) -> "EventLogWriter":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _atomic_append(self, line: str) -> None:
        """Atomically append a single line to the log file.

        Strategy: write to a temporary file on the same filesystem, then
        rename over the actual path.  On POSIX ``rename()`` is atomic
        as long as source and destination live on the same mount point.
        """
        tmp = tempfile.NamedTemporaryFile(
            mode="a",
            encoding="utf-8",
            dir=str(self.path.parent),
            prefix=".event_log_tmp_",
            suffix=".jsonl",
            delete=False,
        )
        try:
            tmp_path = Path(tmp.name)

            # If the real file already exists, copy its content first so
            # we do a safe atomic replacement instead of truncation.
            if self.path.exists():
                shutil.copy2(str(self.path), str(tmp_path))

            # Append the new line
            tmp.write(line)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()

            # Atomic rename
            os.replace(str(tmp_path), str(self.path))
        except BaseException:
            # Clean up temp file on error
            tmp.close()
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def _maybe_rotate(self) -> None:
        """Rotate the log file if it exceeds *max_bytes*."""
        if self.max_bytes <= 0:
            return
        if not self.path.exists():
            return

        try:
            size = self.path.stat().st_size
        except OSError:
            return

        if size < self.max_bytes:
            return

        # Remove the oldest backup if we've reached the limit
        last = self.path.with_suffix(f".{self.backup_count}{self.path.suffix}")
        last.unlink(missing_ok=True)

        # Shift existing backups: .2 → .3, .1 → .2, ...
        for i in range(self.backup_count - 1, 0, -1):
            src = self.path.with_suffix(f".{i}{self.path.suffix}")
            dst = self.path.with_suffix(f".{i + 1}{self.path.suffix}")
            if src.exists():
                shutil.move(str(src), str(dst))

        # Rename current log → .1
        backup_path = self.path.with_suffix(f".1{self.path.suffix}")
        shutil.move(str(self.path), str(backup_path))

    def _acquire_file_lock(self) -> None:
        """Acquire an exclusive advisory lock on the lock file.

        Uses POSIX ``fcntl.flock`` for cross-process synchronisation.
        On Windows this would need ``msvcrt.locking``; for the initial
        implementation we only support POSIX platforms.
        """
        if self._lock_fd is None:
            self._lock_fd = os.open(
                str(self._lock_path),
                os.O_CREAT | os.O_RDWR,
                0o644,
            )
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)

    def _release_file_lock(self) -> None:
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

    def _sync_parent(self) -> None:
        """fsync the parent directory so the rename is durable."""
        try:
            dir_fd = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
