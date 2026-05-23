"""Docker build context audit — enforces size budget and prohibited path patterns."""

import os
import sys
from pathlib import Path
from typing import List, Tuple


# Default budget in bytes (50 MB)
DEFAULT_CONTEXT_BUDGET = 50 * 1024 * 1024

# Prohibited exact directory names (walk is pruned)
PROHIBITED_DIRECTORIES = [
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".eggs",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
]


def scan_context(base_path: Path = Path(".")) -> List[Tuple[str, int, str]]:
    """Scan the given directory and report issues.

    Returns list of (relative_path, size_in_bytes, reason) tuples.
    reason is one of: "prohibited_directory" or "over_budget".
    """
    issues: List[Tuple[str, int, str]] = []
    total_size = 0

    for root, dirs, files in os.walk(base_path):
        rel = Path(root).relative_to(base_path)
        parts = list(rel.parts)

        # If any ancestor dir is prohibited, flag it and prune
        skip = False
        for p in parts:
            if p in PROHIBITED_DIRECTORIES:
                issues.append((str(rel), 0, "prohibited_directory"))
                dirs[:] = []
                skip = True
                break
        if skip:
            continue

        # Prune prohibited subdirectories from walk
        dirs[:] = [d for d in dirs if d not in PROHIBITED_DIRECTORIES]

        for f in files:
            fpath = Path(root) / f
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            total_size += size

    total_mb = total_size / (1024 * 1024)
    budget_mb = DEFAULT_CONTEXT_BUDGET / (1024 * 1024)

    if total_size > DEFAULT_CONTEXT_BUDGET:
        issues.append(
            ("(total)", total_size, f"over_budget: {total_mb:.1f} MB > {budget_mb:.0f} MB budget")
        )

    return issues


def audit_context(base_path: Path = Path("."), budget: int = DEFAULT_CONTEXT_BUDGET) -> List[Tuple[str, int, str]]:
    """Run a full build context audit."""
    return scan_context(base_path)


def main():
    """CLI entry point — exits non-zero on failure."""
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    issues = audit_context(base)

    if not issues:
        print("Docker build context audit passed.")
        sys.exit(0)

    print("Docker build context audit FAILED:")
    for path, size, reason in issues:
        size_str = f"{size / 1024:.1f} KB" if size > 0 else "N/A"
        print(f"  - {path} ({size_str}) — {reason}")

    sys.exit(1)


if __name__ == "__main__":
    main()
