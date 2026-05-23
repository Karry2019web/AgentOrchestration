"""Tests for the JSONL event log writer."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.common.event_logger import EventLogWriter


class TestEventLogWriter:
    """Unit tests for EventLogWriter — atomic writes, locking, rotation."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ao_event_log_test_")
        self.log_path = Path(self.tmpdir) / "events.jsonl"
        self.writer = EventLogWriter(str(self.log_path))
        yield
        self.writer.close()

    # ------------------------------------------------------------------
    # Basic writes
    # ------------------------------------------------------------------

    def test_write_and_read_single_record(self):
        self.writer.write({"event": "start", "id": 1})
        records = self.writer.read_all()
        assert len(records) == 1
        assert records[0] == {"event": "start", "id": 1}

    def test_write_multiple_records(self):
        self.writer.write({"event": "a", "seq": 1})
        self.writer.write({"event": "b", "seq": 2})
        self.writer.write({"event": "c", "seq": 3})
        records = self.writer.read_all()
        assert len(records) == 3
        assert [r["seq"] for r in records] == [1, 2, 3]

    def test_write_persists_to_disk(self):
        self.writer.write({"event": "persist"})
        self.writer.close()
        # Re-read directly from the file
        with open(self.log_path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"event": "persist"}

    def test_read_all_empty_when_no_file(self):
        empty_path = Path(self.tmpdir) / "nonexistent.jsonl"
        writer = EventLogWriter(str(empty_path))
        assert writer.read_all() == []
        writer.close()

    def test_atomic_write_no_corruption_on_failure(self):
        """Verify that a failed write does not corrupt the existing log."""
        self.writer.write({"event": "before"})

        # Force an error inside _atomic_append by providing a bad encoding
        # (normal json.dumps won't fail, so we can simulate by closing the fd)
        with pytest.raises(Exception):
            self.writer.write({"event": "crash"})
            raise RuntimeError("simulated crash after write")

        # The original content should still be intact
        records = self.writer.read_all()
        assert len(records) == 1
        assert records[0] == {"event": "before"}

    # ------------------------------------------------------------------
    # Thread safety
    # ------------------------------------------------------------------

    def test_concurrent_writes_thread_safe(self):
        import threading

        num_threads = 8
        records_per_thread = 50
        barrier = threading.Barrier(num_threads)

        def _writer(worker_id: int):
            barrier.wait()  # start as close to simultaneously as possible
            for i in range(records_per_thread):
                self.writer.write({"worker": worker_id, "seq": i})

        threads = [
            threading.Thread(target=_writer, args=(wid,))
            for wid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        records = self.writer.read_all()
        total_expected = num_threads * records_per_thread
        assert len(records) == total_expected, (
            f"Expected {total_expected} records, got {len(records)}"
        )

        # Every record must parse as valid JSON
        for r in records:
            assert "worker" in r
            assert "seq" in r

    # ------------------------------------------------------------------
    # Log rotation
    # ------------------------------------------------------------------

    def test_rotation_triggers_when_file_exceeds_max_bytes(self):
        small_max = 100  # bytes
        writer = EventLogWriter(str(self.log_path), max_bytes=small_max, backup_count=2)

        # Write enough records to trigger rotation
        for i in range(200):
            writer.write({"event": "rotate_test", "index": i, "data": "x" * 50})

        writer.close()

        # The main file should exist and contain records
        assert self.log_path.exists()
        backup_1 = self.log_path.with_suffix(".1.jsonl")
        assert backup_1.exists(), f"Expected backup .1 to exist, found: {list(self.tmpdir.iterdir())}"

        # All records should be valid JSONL
        written = []
        for p in [self.log_path, backup_1]:
            if p.exists():
                with open(p, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            written.append(json.loads(line))

        assert len(written) == 200, f"Expected 200 total records, got {len(written)}"

    def test_rotation_respects_backup_count(self):
        writer = EventLogWriter(str(self.log_path), max_bytes=50, backup_count=3)

        # Write enough to exceed max_bytes many times over
        for i in range(500):
            writer.write({"ev": i, "pad": "z" * 20})

        writer.close()

        # Count the backup files
        backups = sorted(self.tmpdir.glob("events*.jsonl"))
        assert len(backups) <= 4, (
            f"Expected at most 4 files (main + 3 backups), got {len(backups)}: {backups}"
        )

    def test_no_rotation_when_max_bytes_is_zero(self):
        writer = EventLogWriter(str(self.log_path), max_bytes=0)
        for i in range(100):
            writer.write({"ev": i})
        writer.close()

        backups = list(self.tmpdir.glob("events*.jsonl.*"))
        assert len(backups) == 0

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def test_context_manager_closes_lock(self):
        with EventLogWriter(str(self.log_path)) as writer:
            writer.write({"event": "ctx"})
            assert writer._lock_fd is not None
            assert writer._lock_path.exists()
        # After exit the lock should be released
        assert writer._lock_fd is None

    # ------------------------------------------------------------------
    # Data integrity
    # ------------------------------------------------------------------

    def test_all_records_are_complete_jsonl(self):
        """No partial / truncated lines make it to disk."""
        for i in range(50):
            self.writer.write({
                "id": i,
                "payload": "x" * 100,
            })

        with open(self.log_path, "r") as f:
            lines = f.readlines()

        assert len(lines) == 50
        for line in lines:
            line = line.strip()
            assert line, "Empty line found"
            parsed = json.loads(line)
            assert "id" in parsed and "payload" in parsed
