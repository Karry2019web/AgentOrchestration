"""CLI entry point for the agent orchestrator."""

import argparse
import sys

from src.common.config import Config
from src.common.logging import configure_logging


def handle_init(name: str) -> int:
    """Initialize a new project."""
    print(f"Initializing project: {name}")
    return 0


def handle_deploy(manifest: str) -> int:
    """Deploy an agent from a manifest file."""
    try:
        if not manifest:
            print("Error: manifest path is required", file=sys.stderr)
            return 1
        print(f"Deploying agent from manifest: {manifest}")
        return 0
    except Exception as e:
        print(f"Deploy failed: {e}", file=sys.stderr)
        return 1


def handle_status(watch: bool = False) -> int:
    """Show agent status."""
    print("Checking agent status...")
    return 0


def handle_logs(agent_id: str, tail: int = 50) -> int:
    """View agent logs."""
    print(f"Fetching logs for agent: {agent_id}")
    return 0


def cli(argv=None) -> int:
    """CLI entry point, returns an exit code."""
    parser = argparse.ArgumentParser(description="Agent Orchestrator CLI")
    parser.add_argument("--config", "-c", help="Path to config file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    init_parser = subparsers.add_parser("init", help="Initialize a new project")
    init_parser.add_argument("name", help="Project name")

    deploy_parser = subparsers.add_parser("deploy", help="Deploy an agent")
    deploy_parser.add_argument("manifest", help="Path to agent manifest file")

    status_parser = subparsers.add_parser("status", help="Show agent status")
    status_parser.add_argument("--watch", "-w", action="store_true", help="Watch mode")

    logs_parser = subparsers.add_parser("logs", help="View agent logs")
    logs_parser.add_argument("agent_id", help="Agent ID")
    logs_parser.add_argument("--tail", "-t", type=int, default=50, help="Number of lines")

    args = parser.parse_args(argv)

    if args.verbose:
        configure_logging("DEBUG")
    else:
        configure_logging("INFO")

    if args.command == "init":
        return handle_init(args.name)
    elif args.command == "deploy":
        return handle_deploy(args.manifest)
    elif args.command == "status":
        return handle_status(watch=args.watch)
    elif args.command == "logs":
        return handle_logs(args.agent_id, tail=args.tail)
    else:
        parser.print_help()
        return 1


def main() -> None:
    """Wrapper that passes the exit code to sys.exit."""
    sys.exit(cli())


if __name__ == "__main__":
    main()
