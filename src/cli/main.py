"""CLI entry point for the agent orchestrator."""

import argparse
import sys
from typing import Optional

from src.common.config import Config
from src.common.logging import configure_logging
from src.sdk.client import OrchestratorClient


def cli(client: Optional[OrchestratorClient] = None):
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

    args = parser.parse_args()

    if args.verbose:
        configure_logging("DEBUG")
    else:
        configure_logging("INFO")

    # Create default client if none injected (production path)
    if client is None:
        client = OrchestratorClient()

    if args.command == "init":
        print(f"Initializing project: {args.name}")
    elif args.command == "deploy":
        print(f"Deploying agent from manifest: {args.manifest}")
        result = client.register_agent(args.manifest, "custom")
        print(f"Agent registered: {result}")
    elif args.command == "status":
        print("Checking agent status...")
        agents = client.list_agents()
        print(f"Active agents: {agents}")
    elif args.command == "logs":
        print(f"Fetching logs for agent: {args.agent_id}")
        agent = client.get_agent(args.agent_id)
        print(f"Agent info: {agent}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    cli()
