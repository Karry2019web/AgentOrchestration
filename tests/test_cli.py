"""Tests for CLI parser construction and CLI behavior."""

from src.cli.main import build_parser


class TestBuildParser:
    def test_creates_argument_parser(self):
        """build_parser returns a configured ArgumentParser."""
        parser = build_parser()
        assert parser is not None
        assert parser.description == "Agent Orchestrator CLI"

    def test_global_options(self):
        """Parser includes --config and --verbose flags."""
        parser = build_parser()
        actions = {a.dest: a for a in parser._actions}
        assert "config" in actions
        assert "verbose" in actions
        assert actions["verbose"].action == "store_true"

    def test_subcommands_exist(self):
        """Parser registers expected subcommands."""
        parser = build_parser()
        subparsers_actions = [
            a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)
        ]
        assert len(subparsers_actions) == 1
        choices = subparsers_actions[0].choices
        assert "init" in choices
        assert "deploy" in choices
        assert "status" in choices
        assert "logs" in choices

    def test_init_subcommand_requires_name(self):
        """init subcommand has a positional 'name' argument."""
        parser = build_parser()
        init_parser = parser._actions[-1].choices["init"]
        names = {a.dest for a in init_parser._actions}
        assert "name" in names

    def test_deploy_subcommand_requires_manifest(self):
        """deploy subcommand has a positional 'manifest' argument."""
        parser = build_parser()
        deploy_parser = parser._actions[-1].choices["deploy"]
        names = {a.dest for a in deploy_parser._actions}
        assert "manifest" in names

    def test_status_has_watch_flag(self):
        """status subcommand has --watch/-w flag."""
        parser = build_parser()
        status_parser = parser._actions[-1].choices["status"]
        watch_action = status_parser._option_string_actions.get("--watch")
        assert watch_action is not None
        assert watch_action.option_strings == ["--watch", "-w"]

    def test_logs_has_agent_id_positional(self):
        """logs subcommand has positional 'agent_id' argument."""
        parser = build_parser()
        logs_parser = parser._actions[-1].choices["logs"]
        names = {a.dest for a in logs_parser._actions}
        assert "agent_id" in names

    def test_logs_has_tail_flag(self):
        """logs subcommand has --tail/-t flag defaulting to 50."""
        parser = build_parser()
        logs_parser = parser._actions[-1].choices["logs"]
        tail_action = logs_parser._option_string_actions.get("--tail")
        assert tail_action is not None
        assert tail_action.default == 50
