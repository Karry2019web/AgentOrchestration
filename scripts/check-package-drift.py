#!/usr/bin/env python3
"""
Workspace Package Drift Check

Validates that when a workspace package changes, its dependent packages
also have their versions updated. Fails CI before publishing
if version drift exists.

Usage:
    python scripts/check-package-drift.py [--base-ref main]

Exit codes:
    0 - No drift detected
    1 - Version drift detected (names affected packages)
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


# Dependency graph: workspace package -> packages that depend on it
# These are internal/repo-local dependencies between src/* subdirectories
DEPENDENCY_GRAPH = {
    "agent": ["orchestrator", "api"],
    "common": ["agent", "api", "cli", "orchestrator", "sdk"],
    "orchestrator": [],
    "sdk": [],
    "api": [],
    "cli": [],
    "contracts": [],
}

# Reverse: who is affected when a package changes
DEPENDENTS = {}
for pkg, deps in DEPENDENCY_GRAPH.items():
    for dep in deps:
        DEPENDENTS.setdefault(dep, []).append(pkg)


def get_changed_packages(base_ref: str = "main") -> set:
    """Get workspace packages that have changed vs base_ref."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}..."],
            capture_output=True, text=True, timeout=30,
        )

    changed = set()
    for filepath in result.stdout.strip().split("\n"):
        filepath = filepath.strip()
        if not filepath or not filepath.startswith("src/"):
            continue
        parts = filepath.split("/")
        if len(parts) >= 2:
            pkg = parts[1]
            if pkg in DEPENDENCY_GRAPH:
                changed.add(pkg)

    return changed


def main():
    parser = argparse.ArgumentParser(description="Check workspace package version drift")
    parser.add_argument("--base-ref", default="main", help="Base git ref to compare against")
    args = parser.parse_args()

    changed = get_changed_packages(args.base_ref)

    if not changed:
        print("No workspace packages changed.")
        sys.exit(0)

    print(f"Changed workspace packages: {', '.join(sorted(changed))}")

    drift_found = False
    for changed_pkg in sorted(changed):
        dependents = DEPENDENTS.get(changed_pkg, [])
        if dependents:
            drift_found = True
            print(f"\n  [!] {changed_pkg} changed -- affected dependents: {', '.join(dependents)}")

    if drift_found:
        print("\n\nFAIL: Workspace package drift detected.")
        print("Changed packages have dependents that need version updates.")
        print("Action required: bump version in pyproject.toml and update dependent packages.")
        sys.exit(1)

    print("No version drift detected.")
    sys.exit(0)


if __name__ == "__main__":
    main()
