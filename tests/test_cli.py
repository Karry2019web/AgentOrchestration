"""Tests for the CLI entry point."""

import sys

import pytest


def test_cli_init_returns_zero():
    """init command exits with code 0."""
    from src.cli.main import handle_init

    class FakeArgs:
        name = "test-project"

    assert handle_init(FakeArgs()) == 0


def test_cli_deploy_returns_zero():
    """deploy command with valid manifest exits with code 0."""
    from src.cli.main import handle_deploy

    class FakeArgs:
        manifest = "manifest.yaml"

    assert handle_deploy(FakeArgs()) == 0


def test_cli_unknown_command_returns_one():
    """An unrecognized subcommand handler returns exit code 1."""
    handlers = {"init": lambda a: 0}
    assert handlers.get("bogus", lambda a: 1)(None) == 1


def test_cli_deploy_failure_returns_one():
    """deploy handler returns exit code 1 when backend fails."""
    from src.cli.main import handle_deploy

    class FakeArgs:
        manifest = "bad.yaml"

    original_print = __builtins__.get("print")
    try:
        # Simulate failure by patching print to raise
        def failing_print(*args, **kwargs):
            raise RuntimeError("orchestrator unreachable")
        __builtins__["print"] = failing_print
        result = handle_deploy(FakeArgs())
        assert result == 1
    finally:
        __builtins__["print"] = original_print
