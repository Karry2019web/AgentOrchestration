"""Tests for the CLI entry point."""

from src.cli.main import build_parser


class TestCliParser:
    def test_build_parser_returns_parser(self):
        """build_parser should return an ArgumentParser."""
        parser = build_parser()
        assert parser is not None
        assert parser.description == "Agent Orchestrator CLI"

    def test_build_parser_has_subcommands(self):
        """build_parser should register expected subcommands."""
        parser = build_parser()
        subparsers_actions = [a for a in parser._actions if a.option_strings is None]
        assert len(subparsers_actions) > 0

    def test_cli_accepts_client_factory(self):
        """cli() should accept an optional client_factory parameter."""
        from src.cli.main import cli
        assert cli.__code__.co_varnames[:1] == ("client_factory",)
