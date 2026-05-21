"""Tests for CLI log tail validation."""

import argparse
import sys
import pytest


def _positive_int(value: str) -> int:
    """Argparse type that validates a non-negative integer."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value!r}")
    if n < 0:
        raise argparse.ArgumentTypeError(f"expected non-negative integer, got {n}")
    return n


class TestPositiveInt:
    """Tests for the _positive_int argparse type."""

    def test_zero_is_valid(self):
        assert _positive_int("0") == 0

    def test_positive_is_valid(self):
        assert _positive_int("50") == 50
        assert _positive_int("1") == 1
        assert _positive_int("999999") == 999999

    def test_negative_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="non-negative"):
            _positive_int("-1")
        with pytest.raises(argparse.ArgumentTypeError, match="non-negative"):
            _positive_int("-5")

    def test_non_numeric_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="invalid integer"):
            _positive_int("abc")
        with pytest.raises(argparse.ArgumentTypeError, match="invalid integer"):
            _positive_int("12.5")
        with pytest.raises(argparse.ArgumentTypeError, match="invalid integer"):
            _positive_int("")

    def test_whitespace_raises(self):
        with pytest.raises(ValueError):
            _positive_int("  ")

    def test_logs_parser_accepts_positive_tail(self):
        """Integration: --tail accepts non-negative values."""
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        logs = sub.add_parser("logs")
        logs.add_argument("--tail", "-t", type=_positive_int, default=50)
        args = parser.parse_args(["logs", "--tail", "10"])
        assert args.tail == 10

    def test_logs_parser_default_tail(self):
        """Integration: default tail value is preserved."""
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        logs = sub.add_parser("logs")
        logs.add_argument("--tail", "-t", type=_positive_int, default=50)
        args = parser.parse_args(["logs"])
        assert args.tail == 50

    def test_logs_parser_rejects_negative_tail(self):
        """Integration: --tail -5 raises."""
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        logs = sub.add_parser("logs")
        logs.add_argument("--tail", "-t", type=_positive_int, default=50)
        with pytest.raises(SystemExit):
            parser.parse_args(["logs", "--tail", "-5"])
