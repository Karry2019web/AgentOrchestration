"""CLI entry point for the agent orchestrator."""

import argparse
import sys

from src.common.config import Config
from src.common.logging import configure_logging
from src.common.validation import assert_valid_agent_id


def cli():
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

    lifecycle_parser = subparsers.add_parser("lifecycle", help="Manage agent lifecycle")
    lifecycle_parser.add_argument("agent_id", help="Agent ID")
    lifecycle_parser.add_argument("action", choices=["start", "stop", "restart"], help="Lifecycle action")

    args = parser.parse_args()

    if args.verbose:
        configure_logging("DEBUG")
    else:
        configure_logging("INFO")

    if args.command == "init":
        print(f"Initializing project: {args.name}")
    elif args.command == "deploy":
        print(f"Deploying agent from manifest: {args.manifest}")
    elif args.command == "status":
        print("Checking agent status...")
    elif args.command == "logs":
        try:
            assert_valid_agent_id(args.agent_id)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Fetching logs for agent: {args.agent_id}")
    elif args.command == "lifecycle":
        try:
            assert_valid_agent_id(args.agent_id)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Performing '{args.action}' on agent: {args.agent_id}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    cli()

# 2026-05-22T12:10:26 update - added agent_id validation for logs and lifecycle commands
