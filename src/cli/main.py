"""CLI entry point for the agent orchestrator."""

import argparse
import json
import sys

from src.common.config import Config
from src.common.logging import configure_logging
from src.common.placement import validate_deployment_manifest


def cli():
    parser = argparse.ArgumentParser(description="Agent Orchestrator CLI")
    parser.add_argument("--config", "-c", help="Path to config file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    init_parser = subparsers.add_parser("init", help="Initialize a new project")
    init_parser.add_argument("name", help="Project name")

    deploy_parser = subparsers.add_parser("deploy", help="Deploy an agent")
    deploy_parser.add_argument("manifest", help="Path to agent manifest file")
    deploy_parser.add_argument("--skip-validation", action="store_true",
                               help="Skip placement policy validation")

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
        print(f"Deploying agent from manifest: {args.manifest}")

        if not args.skip_validation:
            try:
                result = validate_deployment_manifest(args.manifest)
                if result.valid:
                    print(f"  Placement policy validation: PASSED")
                    print(f"  Deployment summary: {result.deployment_summary}")
                else:
                    print(f"  Placement policy validation: FAILED")
                    for v in result.violations:
                        sev = "ERROR" if v.severity.value == "error" else "WARN"
                        print(f"    [{sev}] {v.field}: {v.message}")
                    print(f"  Deployment aborted due to placement policy violations.")
                    sys.exit(1)
            except FileNotFoundError:
                print(f"  Error: Manifest file '{args.manifest}' not found.")
                sys.exit(1)
            except json.JSONDecodeError as e:
                print(f"  Error: Invalid JSON in manifest file: {e}")
                sys.exit(1)
        else:
            print(f"  Placement policy validation: SKIPPED")

    elif args.command == "status":
        print("Checking agent status...")
    elif args.command == "logs":
        print(f"Fetching logs for agent: {args.agent_id}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    cli()
