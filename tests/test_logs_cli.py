"""Tests for the CLI logs command tail limit."""

import pytest

from src.cli.main import MAX_LOG_TAIL


class TestCliLogsTail:
    def test_constant_defined(self):
        """MAX_LOG_TAIL should be a positive integer."""
        assert isinstance(MAX_LOG_TAIL, int)
        assert MAX_LOG_TAIL > 0

    def test_constant_value(self):
        """MAX_LOG_TAIL should be set to 10000."""
        assert MAX_LOG_TAIL == 10000

    def test_reasonable_limit(self):
        """MAX_LOG_TAIL should be within a sensible range for log tailing."""
        assert 100 <= MAX_LOG_TAIL <= 1000000
