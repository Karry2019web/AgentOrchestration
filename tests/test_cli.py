"""Tests for CLI validation."""

import argparse

from src.cli.main import non_negative_int


def test_non_negative_int_valid():
    """Test that valid non-negative integers are accepted."""
    assert non_negative_int("0") == 0
    assert non_negative_int("50") == 50
    assert non_negative_int("100") == 100
    assert non_negative_int("999999") == 999999


def test_non_negative_int_negative():
    """Test that negative values are rejected."""
    try:
        non_negative_int("-1")
        assert False, "Should have raised"
    except argparse.ArgumentTypeError as e:
        assert "must be >= 0" in str(e)

    try:
        non_negative_int("-5")
        assert False, "Should have raised"
    except argparse.ArgumentTypeError as e:
        assert "must be >= 0" in str(e)


def test_non_negative_int_invalid():
    """Test that non-integer values are rejected."""
    try:
        non_negative_int("abc")
        assert False, "Should have raised"
    except argparse.ArgumentTypeError as e:
        assert "not a valid integer" in str(e)

    try:
        non_negative_int("")
        assert False, "Should have raised"
    except argparse.ArgumentTypeError as e:
        assert "not a valid integer" in str(e)

    try:
        non_negative_int("12.5")
        assert False, "Should have raised"
    except argparse.ArgumentTypeError as e:
        assert "not a valid integer" in str(e)


def test_cli_imports():
    """Verify the CLI module imports correctly."""
    from src.cli import main
    assert hasattr(main, "cli")
    assert hasattr(main, "non_negative_int")
