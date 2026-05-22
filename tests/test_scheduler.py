"""Tests for TaskScheduler batch acknowledgement ownership."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from orchestrator.scheduler import TaskScheduler
from uuid import uuid4


def test_batch_acknowledge_success():
    s = TaskScheduler()
    tid = str(uuid4())
    s._in_flight[tid] = {"id": tid}
    s._owner[tid] = "worker-1"
    result = s.batch_acknowledge([tid], "worker-1")
    assert result[tid] is True


def test_batch_acknowledge_rejects_wrong_owner():
    s = TaskScheduler()
    tid = str(uuid4())
    s._in_flight[tid] = {"id": tid}
    s._owner[tid] = "worker-1"
    result = s.batch_acknowledge([tid], "worker-2")
    assert result[tid] is False


def test_complete_known():
    s = TaskScheduler()
    tid = str(uuid4())
    s._in_flight[tid] = {"id": tid}
    assert s.complete(tid) is True


def test_complete_unknown():
    s = TaskScheduler()
    assert s.complete("unknown") is False
