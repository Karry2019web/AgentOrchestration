"""Tests for the CLI module."""
import pytest
from src.cli.main import cli, handle_init, handle_deploy, handle_status, handle_logs


class TestCliHandlers:
    def test_handle_init_returns_zero(self):
        """A regression test covering the CLI handler contract."""
        result = handle_init("test-project")
        assert result == 0, "init handler should return 0 on success"

    def test_handle_deploy_returns_zero_for_valid_manifest(self):
        result = handle_deploy("manifest.yaml")
        assert result == 0, "deploy handler should return 0 on success"

    def test_handle_deploy_returns_one_for_empty_manifest(self):
        result = handle_deploy("")
        assert result == 1, "deploy handler should return 1 when manifest is empty"

    def test_handle_status_returns_zero(self):
        result = handle_status()
        assert result == 0, "status handler should return 0 on success"

    def test_handle_logs_returns_zero(self):
        result = handle_logs("agent-123")
        assert result == 0, "logs handler should return 0 on success"

    def test_handle_logs_with_tail(self):
        result = handle_logs("agent-123", tail=100)
        assert result == 0

    def test_cli_init_returns_zero(self):
        result = cli(["init", "my-project"])
        assert result == 0

    def test_cli_deploy_returns_zero(self):
        result = cli(["deploy", "manifest.yaml"])
        assert result == 0

    def test_cli_unknown_command_returns_one(self):
        result = cli(["unknown"])
        assert result == 1, "unknown command should return exit code 1"

    def test_cli_no_args_returns_one(self):
        result = cli([])
        assert result == 1, "no arguments should return exit code 1"
