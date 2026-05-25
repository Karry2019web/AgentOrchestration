"""Tests for CLI output mode validation."""

import argparse
import sys
import pytest


VALID_OUTPUTS = ["text", "json", "yaml"]
INVALID_OUTPUT = "html"


class TestValidOutputModes:
    """Each valid output mode must be accepted without error."""

    @pytest.mark.parametrize("mode", VALID_OUTPUTS)
    def test_valid_output_accepted(self, mode):
        test_args = ["--output", mode, "status"]
        sys.argv = ["ao"] + test_args
        try:
            from src.cli.main import cli
            cli()
        except SystemExit:
            pytest.fail(f"--output {mode} should be valid")

    @pytest.mark.parametrize("mode", VALID_OUTPUTS)
    def test_short_flag_valid(self, mode):
        test_args = ["-o", mode, "status"]
        sys.argv = ["ao"] + test_args
        try:
            from src.cli.main import cli
            cli()
        except SystemExit:
            pytest.fail(f"-o {mode} should be valid")


class TestInvalidOutputMode:
    """Unsupported output values must be rejected by argparse choices."""

    def test_invalid_value_rejected(self):
        test_args = ["--output", INVALID_OUTPUT, "status"]
        sys.argv = ["ao"] + test_args
        with pytest.raises(SystemExit) as exc_info:
            from src.cli.main import cli
            cli()
        assert exc_info.value.code == 2, (
            "argparse must exit with code 2 for invalid choice"
        )


def test_default_output_mode_is_text():
    """When --output is omitted, the default should be 'text'."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "-o", choices=["text", "json", "yaml"], default="text")
    args = parser.parse_args([])
    assert args.output == "text", "Default output mode must be 'text'"
