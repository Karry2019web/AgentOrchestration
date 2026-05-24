"""Tests for CheckpointStore — idempotent checkpoint writes."""

import hashlib

import pytest

from src.orchestrator.checkpoint import CheckpointStore, CheckpointKey


class TestCheckpointKey:
    def test_deterministic_key(self):
        k1 = CheckpointKey("task-1", "build", 1)
        k2 = CheckpointKey("task-1", "build", 1)
        assert k1.key == k2.key

    def test_different_task_different_key(self):
        k1 = CheckpointKey("task-1", "build", 1)
        k2 = CheckpointKey("task-2", "build", 1)
        assert k1.key != k2.key

    def test_different_step_different_key(self):
        k1 = CheckpointKey("task-1", "build", 1)
        k2 = CheckpointKey("task-1", "deploy", 1)
        assert k1.key != k2.key

    def test_different_attempt_different_key(self):
        k1 = CheckpointKey("task-1", "build", 1)
        k2 = CheckpointKey("task-1", "build", 2)
        assert k1.key != k2.key

    def test_composite_key_format(self):
        k = CheckpointKey("task-42", "test", 3)
        assert k.composite_key == "cp:task-42:test:3"

    def test_key_uses_sha256(self):
        k = CheckpointKey("t", "s", 1)
        expected = hashlib.sha256("t:s:1".encode()).hexdigest()
        assert k.key == expected


class TestCheckpointStore:
    def setup_method(self):
        self.store = CheckpointStore()

    def test_write_and_read(self):
        self.store.write("task-1", "build", 1, {"status": "ok", "output": "built"})
        result = self.store.read("task-1", "build", 1)
        assert result is not None
        assert result["data"]["status"] == "ok"
        assert result["version"] == 1

    def test_idempotent_write_retries(self):
        data = {"status": "ok", "output": "built"}
        self.store.write("task-1", "build", 1, data)
        self.store.write("task-1", "build", 1, data)
        assert self.store.count() == 1
        result = self.store.read("task-1", "build", 1)
        assert result is not None
        assert result["data"]["status"] == "ok"

    def test_idempotent_write_multiple_retries(self):
        data = {"progress": 42}
        for _ in range(5):
            self.store.write("task-1", "build", 1, data)
        assert self.store.count() == 1

    def test_digest_mismatch_raises(self):
        self.store.write("task-1", "build", 1, {"status": "ok"})
        with pytest.raises(ValueError, match="digest mismatch"):
            self.store.write("task-1", "build", 1, {"status": "different"})

    def test_digest_mismatch_different_step_ok(self):
        self.store.write("task-1", "build", 1, {"status": "ok"})
        self.store.write("task-1", "deploy", 1, {"status": "different"})
        assert self.store.count() == 2

    def test_resume_returns_latest_attempt(self):
        self.store.write("task-1", "build", 1, {"progress": 10})
        self.store.write("task-1", "build", 2, {"progress": 50})
        self.store.write("task-1", "build", 3, {"progress": 90})
        result = self.store.resume("task-1")
        assert result is not None
        assert result["data"]["progress"] == 90
        assert result["key"]["attempt"] == 3

    def test_resume_with_single_checkpoint(self):
        self.store.write("task-1", "build", 1, {"progress": 25})
        result = self.store.resume("task-1")
        assert result is not None
        assert result["data"]["progress"] == 25

    def test_resume_no_checkpoints(self):
        result = self.store.resume("non-existent-task")
        assert result is None

    def test_exists(self):
        self.store.write("task-1", "build", 1, {"status": "ok"})
        assert self.store.exists("task-1", "build", 1)
        assert not self.store.exists("task-1", "build", 2)

    def test_timeout_and_retry_scenario(self):
        self.store.write("task-1", "build", 1, {"status": "in_progress", "progress": 30})
        self.store.write("task-1", "build", 1, {"status": "in_progress", "progress": 30})
        assert self.store.count() == 1
        assert self.store.exists("task-1", "build", 1)
        result = self.store.resume("task-1")
        assert result is not None
        assert result["data"]["progress"] == 30

    def test_overwrite_with_same_data_advances_version(self):
        data = {"status": "ok"}
        ck1 = self.store.write("task-1", "build", 1, data)
        result1 = self.store.read("task-1", "build", 1)
        v1 = result1["version"]
        ck2 = self.store.write("task-1", "build", 1, data)
        result2 = self.store.read("task-1", "build", 1)
        v2 = result2["version"]
        assert ck1.key == ck2.key
        assert v2 > v1

    def test_multiple_tasks_independent(self):
        self.store.write("task-1", "build", 1, {"data": "a"})
        self.store.write("task-2", "build", 1, {"data": "b"})
        assert self.store.count() == 2
        r1 = self.store.read("task-1", "build", 1)
        r2 = self.store.read("task-2", "build", 1)
        assert r1["data"]["data"] == "a"
        assert r2["data"]["data"] == "b"

    def test_clear_store(self):
        self.store.write("task-1", "build", 1, {"x": 1})
        self.store.write("task-1", "build", 2, {"x": 2})
        assert self.store.count() == 2
        self.store.clear()
        assert self.store.count() == 0
        assert self.store.resume("task-1") is None
