"""Tests for CLI argument validation."""

import pytest
from argparse import ArgumentTypeError

from src.cli.main import _non_negative_int


class TestNonNegativeInt:
    """Tests for the _non_negative_int type validator."""

    def test_accepts_zero(self):
        assert _non_negative_int("0") == 0

    def test_accepts_positive(self):
        assert _non_negative_int("42") == 42
        assert _non_negative_int("1") == 1
        assert _non_negative_int("100") == 100

    def test_rejects_negative(self):
        with pytest.raises(ArgumentTypeError, match="non-negative"):
            _non_negative_int("-5")

    def test_rejects_negative_one(self):
        with pytest.raises(ArgumentTypeError, match="non-negative"):
            _non_negative_int("-1")

    def test_rejects_non_numeric(self):
        with pytest.raises(ArgumentTypeError, match="invalid int"):
            _non_negative_int("abc")

    def test_rejects_float_string(self):
        with pytest.raises(ArgumentTypeError, match="invalid int"):
            _non_negative_int("4.5")

    def test_rejects_empty_string(self):
        with pytest.raises(ArgumentTypeError, match="invalid int"):
            _non_negative_int("")

