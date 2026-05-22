"""Tests for SDK decorators module."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sdk.decorators import task


def test_zero_timeout_raises():
    raised = False
    try:
        @task(timeout=0)
        def dummy():
            pass
    except ValueError:
        raised = True
    assert raised, "timeout=0 should raise ValueError"


def test_negative_timeout_raises():
    raised = False
    try:
        @task(timeout=-5)
        def dummy():
            pass
    except ValueError:
        raised = True
    assert raised, "negative timeout should raise ValueError"


def test_positive_timeout_ok():
    result = task(timeout=30)
    assert result is not None, "positive timeout should not raise"


def test_default_timeout_ok():
    result = task()
    assert result is not None, "default timeout should not raise"


def test_large_timeout_ok():
    result = task(timeout=86400)
    assert result is not None, "large timeout should not raise"
