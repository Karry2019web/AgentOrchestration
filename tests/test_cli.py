"""Tests for CLI parser construction."""

import argparse
import pytest
from src.cli.main import build_parser


class TestCliParser:
    """Regression tests for CLI parser construction."""

    def test_build_parser_returns_argument_parser(self):
        """build_parser() should return an ArgumentParser instance."""
        parser = build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_has_config_option(self):
        """Parser should expose --config / -c for config file path."""
        parser = build_parser()
        actions = {a.dest: a for a in parser._actions}
        assert "config" in actions
        assert actions["config"].option_strings == ["--config", "-c"]

    def test_parser_has_verbose_flag(self):
        """Parser should expose --verbose / -v as a store_true flag."""
        parser = build_parser()
        actions = {a.dest: a for a in parser._actions}
        assert "verbose" in actions
        assert actions["verbose"].option_strings == ["--verbose", "-v"]
        assert actions["verbose"].const is True

    def test_parser_has_init_subcommand(self):
        """Parser should have an 'init' subcommand with a 'name' positional."""
        parser = build_parser()
        subparsers_actions = [
            a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)
        ]
        assert len(subparsers_actions) == 1
        subparsers = subparsers_actions[0]
        assert "init" in subparsers.choices
        init_parser = subparsers.choices["init"]
        init_actions = {a.dest: a for a in init_parser._actions}
        assert "name" in init_actions

    def test_parser_has_deploy_subcommand(self):
        """Parser should have a 'deploy' subcommand with a 'manifest' positional."""
        parser = build_parser()
        subparsers = [a for a in parser._actions
                      if isinstance(a, argparse._SubParsersAction)][0]
        assert "deploy" in subparsers.choices
        deploy_parser = subparsers.choices["deploy"]
        deploy_actions = {a.dest: a for a in deploy_parser._actions}
        assert "manifest" in deploy_actions

    def test_parser_has_status_subcommand(self):
        """Parser should have a 'status' subcommand with --watch flag."""
        parser = build_parser()
        subparsers = [a for a in parser._actions
                      if isinstance(a, argparse._SubParsersAction)][0]
        assert "status" in subparsers.choices
        status_parser = subparsers.choices["status"]
        status_actions = {a.dest: a for a in status_parser._actions}
        assert "watch" in status_actions

    def test_parser_has_logs_subcommand(self):
        """Parser should have a 'logs' subcommand with agent_id and --tail."""
        parser = build_parser()
        subparsers = [a for a in parser._actions
                      if isinstance(a, argparse._SubParsersAction)][0]
        assert "logs" in subparsers.choices
        logs_parser = subparsers.choices["logs"]
        logs_actions = {a.dest: a for a in logs_parser._actions}
        assert "agent_id" in logs_actions
        assert "tail" in logs_actions

    def test_run_init_via_cli(self, monkeypatch, capsys):
        """cli() should handle the 'init' command correctly."""
        from src.cli.main import cli
        monkeypatch.setattr("sys.argv", ["agent", "init", "my_project"])
        cli()
        captured = capsys.readouterr()
        assert "Initializing project" in captured.out
        assert "my_project" in captured.out

    def test_help_exits_with_code_one(self, monkeypatch):
        """Running cli() with no args should print help and exit with code 1."""
        from src.cli.main import cli
        monkeypatch.setattr("sys.argv", ["agent"])
        with pytest.raises(SystemExit) as exc:
            cli()
        assert exc.value.code == 1
