#!/usr/bin/env python3
"""
Workspace Package Drift Validator

Detects when internal package changes require dependent package version bumps.
Fails CI when a changed package's dependent consumers have outdated version 
references that would cause runtime resolution failures.

Usage:
    python scripts/validate_package_drift.py [--compare-branch <branch>]

Acceptance criteria:
1. Changed internal packages require compatible dependent version updates.
2. Release validation fails before package publishing on version drift.
3. The failure output names affected package pairs.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# Map of internal package names to their source directories and consumer packages
# These are the internal sub-packages that form the "workspace"
INTERNAL_PACKAGES = {
    "agent": {
        "path": "src/agent",
        "consumers": {"sdk", "api", "orchestrator", "cli"},
        "consumed_by": {"orchestrator": "src.orchestrator"},
    },
    "sdk": {
        "path": "src/sdk",
        "consumers": {"api", "cli"},
        "consumed_by": {"cli": "src.cli", "api": "src.api"},
    },
    "api": {
        "path": "src/api",
        "consumers": {"cli"},
        "consumed_by": {"cli": "src.cli"},
    },
    "orchestrator": {
        "path": "src/orchestrator",
        "consumers": {"api", "cli"},
        "consumed_by": {"api": "src.api"},
    },
    "common": {
        "path": "src/common",
        "consumers": {"agent", "sdk", "api", "orchestrator", "cli"},
        "consumed_by": {"agent": "src.agent", "sdk": "src.sdk", "api": "src.api", "orchestrator": "src.orchestrator", "cli": "src.cli"},
    },
    "cli": {
        "path": "src/cli",
        "consumers": set(),
        "consumed_by": {},
    },
}


def get_current_version() -> str:
    """Read the current version from pyproject.toml."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    content = pyproject_path.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        print("ERROR: Could not find version in pyproject.toml")
        sys.exit(1)
    return match.group(1)


def get_changed_files(compare_branch: str = "origin/main") -> Set[str]:
    """Get files changed compared to the base branch."""
    result = subprocess.run(
        ["git", "diff", "--name-only", compare_branch],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    if result.returncode != 0:
        # Fallback: if git not available, list all source files
        print(f"Warning: git diff failed ({result.stderr.strip()}), checking all src files")
        changed = set()
        for pkg_name, pkg_info in INTERNAL_PACKAGES.items():
            pkg_path = REPO_ROOT / pkg_info["path"]
            if pkg_path.exists():
                for f in pkg_path.rglob("*.py"):
                    changed.add(str(f.relative_to(REPO_ROOT)))
        return changed
    
    return {f.strip() for f in result.stdout.strip().split("\n") if f.strip()}


def identify_changed_packages(changed_files: Set[str]) -> Dict[str, List[str]]:
    """Map changed files to internal packages they belong to."""
    changed_pkgs: Dict[str, List[str]] = {}
    
    for file_path in changed_files:
        for pkg_name, pkg_info in INTERNAL_PACKAGES.items():
            if file_path.startswith(pkg_info["path"]):
                if pkg_name not in changed_pkgs:
                    changed_pkgs[pkg_name] = []
                changed_pkgs[pkg_name].append(file_path)
    
    return changed_pkgs


def check_pypi_version_drift() -> Optional[str]:
    """Check if the local version matches what's published on PyPI.
    
    Returns None if not published or same version, error message if drift detected.
    """
    current_version = get_current_version()
    
    # Check via pip index
    result = subprocess.run(
        [sys.executable, "-m", "pip", "index", "versions", "agent-orchestrator"],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        # Parse available versions
        available_match = re.search(r"Available versions:\s*(.+?)(?:\n|$)", result.stdout)
        if available_match:
            available_versions = available_match.group(1).split(",")
            available_versions = [v.strip() for v in available_versions]
            
            if current_version in available_versions:
                return (
                    f"Version drift detected: {current_version} is already published on PyPI.\n"
                    f"Changes in the workspace require a version bump before publishing.\n"
                    f"Update the version in pyproject.toml before merging."
                )
    
    return None


def get_package_dependency_changes(changed_pkgs: Dict[str, List[str]]) -> List[Dict]:
    """Analyze changed packages and determine if their consumers need version updates."""
    findings: List[Dict] = []
    
    for pkg_name, changed_files in changed_pkgs.items():
        pkg_info = INTERNAL_PACKAGES.get(pkg_name)
        if not pkg_info:
            continue
        
        consumers = pkg_info.get("consumers", set())
        for consumer in consumers:
            # Check if the consumer references the changed package
            consumed_by = pkg_info.get("consumed_by", {})
            consumer_module = consumed_by.get(consumer)
            if not consumer_module:
                continue
            
            # Look for import paths that reference this changed package
            consumer_pkg_path = consumer_module.replace(".", "/").replace("src.", "src/")
            consumer_dir = REPO_ROOT / consumer_pkg_path
            
            has_ref = False
            version_ref_line = ""
            for f in consumer_dir.rglob("*.py"):
                content = f.read_text()
                for line in content.split("\n"):
                    if f"from {pkg_info['path'].replace('/', '.')}" in line and "import" in line:
                        has_ref = True
                        version_ref_line = line.strip()
                        break
                if has_ref:
                    break
            
            if has_ref:
                findings.append({
                    "changed_package": pkg_name,
                    "changed_files": changed_files,
                    "consumer": consumer,
                    "consumer_path": consumer_module,
                    "version_reference": version_ref_line,
                })
    
    return findings


def main():
    parser = argparse.ArgumentParser(description="Validate workspace package version drift")
    parser.add_argument("--compare-branch", default="origin/main",
                       help="Branch to compare against (default: origin/main)")
    parser.add_argument("--ci", action="store_true",
                       help="Run in CI mode (exit with error code on drift)")
    args = parser.parse_args()
    
    current_version = get_current_version()
    print(f"Current package version: {current_version}")
    print()
    
    # Step 1: Get changed files
    try:
        changed_files = get_changed_files(args.compare_branch)
    except Exception as e:
        print(f"Warning: Could not get changed files ({e})")
        changed_files = set()
    
    if not changed_files:
        print("No changed files detected - skipping drift check.")
        return
    
    print(f"Changed files ({len(changed_files)}):")
    for f in sorted(changed_files):
        print(f"  {f}")
    print()
    
    # Step 2: Identify changed packages
    changed_pkgs = identify_changed_packages(changed_files)
    
    if not changed_pkgs:
        print("No internal workspace packages changed - no drift check needed.")
        return
    
    print("Changed workspace packages:")
    for pkg_name, files in sorted(changed_pkgs.items()):
        print(f"  {pkg_name}: {len(files)} file(s)")
        for f in files:
            print(f"    - {f}")
    print()
    
    # Step 3: Check for version drift
    drift_found = False
    findings = get_package_dependency_changes(changed_pkgs)
    
    if findings:
        print("Package dependency changes detected:")
        for f in findings:
            print(f"  Package '{f['changed_package']}' changed - consumer '{f['consumer']}' imports from it:")
            print(f"    {f['version_reference']}")
        drift_found = True
    else:
        print("No inter-package dependency drift detected.")
    
    # Step 4: Check PyPI version drift (only if packages changed)
    if changed_pkgs:
        pypi_drift = check_pypi_version_drift()
        if pypi_drift:
            print(f"\n{pypi_drift}")
            drift_found = True
    
    # Step 5: Report affected pairs
    if findings:
        print("\nAffected package pairs (changed -> consumer):")
        for f in findings:
            print(f"  {f['changed_package']} -> {f['consumer']}")
        print()
    
    if drift_found:
        print("ERROR: WORKSPACE PACKAGE DRIFT DETECTED")
        print("Fix: Update version in pyproject.toml and update consumer version references before merging.")
        if args.ci:
            sys.exit(1)
    else:
        print("OK: No workspace package drift detected")


if __name__ == "__main__":
    main()
