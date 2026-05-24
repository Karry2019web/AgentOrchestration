"""CLI entry point for the agent orchestrator."""

import argparse
import json
import sys

from src.common.config import Config
from src.common.logging import configure_logging
from src.deploy.placement import format_validation_summary, validate_manifest


def cli():
    parser = argparse.ArgumentParser(description="Agent Orchestrator CLI")
    parser.add_argument("--config", "-c", help="Path to config file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    init_parser = subparsers.add_parser("init", help="Initialize a new project")
    init_parser.add_argument("name", help="Project name")

    deploy_parser = subparsers.add_parser("deploy", help="Deploy an agent")
    deploy_parser.add_argument("manifest", help="Path to agent manifest file")
    deploy_parser.add_argument("--validate-only", action="store_true",
                               help="Validate placement policy without deploying")

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

    if args.command == "init":
        print(f"Initializing project: {args.name}")
    elif args.command == "deploy":
        if not args.manifest:
            print("Error: manifest path required")
            sys.exit(1)
        try:
            with open(args.manifest) as f:
                manifest = json.load(f)
        except FileNotFoundError:
            print(f"Error: manifest file not found: {args.manifest}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in manifest: {e}")
            sys.exit(1)

        print("=== Deployment Summary ===")
        print(format_validation_summary(manifest))
        print()

        errors = validate_manifest(manifest)
        if errors:
            print("Placement policy validation FAILED:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)

        if args.validate_only:
            print("Validation passed. Skipping deployment (--validate-only).")
        else:
            print(f"Deploying agent from manifest: {args.manifest}")
    elif args.command == "status":
        print("Checking agent status...")
    elif args.command == "logs":
        print(f"Fetching logs for agent: {args.agent_id}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    cli()
