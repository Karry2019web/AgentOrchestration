"""Tests for CLI main module."""

import pytest
from argparse import ArgumentTypeError


class TestPositiveInt:
    """Tests for the _positive_int validator used in --tail."""

    def test_positive_int_valid(self):
        """Test that positive int values are accepted."""
        from src.cli.main import _positive_int
        assert _positive_int("0") == 0
        assert _positive_int("50") == 50
        assert _positive_int("1000") == 1000

    def test_positive_int_rejects_negative(self):
        """Test that negative int values raise error."""
        from src.cli.main import _positive_int
        with pytest.raises(ArgumentTypeError, match="must be >= 0"):
            _positive_int("-5")

    def test_positive_int_rejects_negative_one(self):
        """Test that -1 also raises error."""
        from src.cli.main import _positive_int
        with pytest.raises(ArgumentTypeError, match="must be >= 0"):
            _positive_int("-1")

    def test_positive_int_rejects_non_int(self):
        """Test that non-integer values raise error."""
        from src.cli.main import _positive_int
        with pytest.raises(ArgumentTypeError, match="invalid int"):
            _positive_int("abc")
