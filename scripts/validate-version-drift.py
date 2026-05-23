#!/usr/bin/env python3
"""
Workspace Package Version Drift Validator

Detects when internal source packages change without a version bump
in pyproject.toml. CI uses local workspace links that mask version drift;
registry consumers will see the stale version.

Exit codes:
    0  — No drift detected (all changed packages have version bumps)
    1  — Version drift detected (output names affected package pairs)

Usage:
    python scripts/validate-version-drift.py [--base-ref <git-ref>]

Default --base-ref is origin/main.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Set, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent

INTERNAL_PACKAGES: dict[str, dict] = {
    "agent": {
        "path": "src/agent",
        "consumers": ["api", "orchestrator", "cli"],
    },
    "sdk": {
        "path": "src/sdk",
        "consumers": ["api", "cli"],
    },
    "api": {
        "path": "src/api",
        "consumers": ["cli"],
    },
    "orchestrator": {
        "path": "src/orchestrator",
        "consumers": ["api", "cli"],
    },
    "common": {
        "path": "src/common",
        "consumers": ["agent", "sdk", "api", "orchestrator", "cli"],
    },
    "contracts": {
        "path": "src/contracts",
        "consumers": ["agent", "sdk", "api", "orchestrator", "cli"],
    },
    "cli": {
        "path": "src/cli",
        "consumers": [],
    },
}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True, timeout=60,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"git {' '.join(args)} failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout.strip()


def get_changed_packages(base_ref: str = "origin/main") -> Set[str]:
    merge_base = _git("merge-base", base_ref, "HEAD")
    diff = _git("diff", "--name-only", merge_base, "HEAD")
    changed_files = {f.strip() for f in diff.splitlines() if f.strip()}

    changed_packages: Set[str] = set()
    for pkg_name, pkg_info in INTERNAL_PACKAGES.items():
        pkg_prefix = pkg_info["path"]
        for cf in changed_files:
            if cf.startswith(pkg_prefix + "/") or cf == pkg_prefix:
                changed_packages.add(pkg_name)
                break

    return changed_packages


def get_version_from_ref(ref: str) -> str:
    content = _git("show", f"{ref}:pyproject.toml")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        print(f"ERROR: Could not find version in pyproject.toml at {ref}", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def get_current_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        print("ERROR: Could not find version in local pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate workspace package version drift"
    )
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Git ref to compare against (default: origin/main)",
    )
    args = parser.parse_args()

    changed = get_changed_packages(args.base_ref)
    if not changed:
        print("No internal packages changed -- no version check needed.")
        return 0

    print(f"Changed packages: {', '.join(sorted(changed))}")

    try:
        old_version = get_version_from_ref(args.base_ref)
    except subprocess.TimeoutExpired:
        old_version = "0.0.0"
    current_version = get_current_version()

    version_bumped = current_version != old_version
    if version_bumped:
        print(f"Version bumped: {old_version} -> {current_version}")
        return 0

    affected_consumers: List[Tuple[str, str]] = []
    for pkg in sorted(changed):
        consumers = INTERNAL_PACKAGES[pkg].get("consumers", [])
        if consumers:
            for consumer in sorted(consumers):
                affected_consumers.append((pkg, consumer))

    if not affected_consumers:
        print("Changed packages have no internal consumers -- drift not applicable.")
        return 0

    print()
    print("VERSION DRIFT DETECTED")
    print("=" * 50)
    print(f"Pyproject.toml version unchanged at {current_version}")
    print("The following package changes require a version bump:")
    print()
    for pkg, consumer in affected_consumers:
        print(f"   * {pkg}/  ->  consumed by {consumer}/")
    print()
    print("To fix: bump the version in pyproject.toml before merging.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
