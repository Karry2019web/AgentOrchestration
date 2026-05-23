#!/usr/bin/env python3
"""Dependency Exception Validator

Validates that every entry in .github/dependency-exceptions.yml
has a valid owner, reason, and non-expired expiration date.

Usage:
    python scripts/validate_dependency_exceptions.py
"""

import os
import sys
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    print("PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


def validate_manifest(path: str = ".github/dependency-exceptions.yml") -> bool:
    """Validate the dependency exception manifest. Returns True if valid."""
    if not os.path.exists(path):
        print(f"No manifest found at {path}")
        return True

    with open(path) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"Invalid YAML in {path}: {e}")
            return False

    if not data:
        print("Empty manifest")
        return True

    exceptions = data.get("exceptions", [])
    if not exceptions:
        print("No exceptions defined")
        return True

    errors = []
    now = datetime.now(timezone.utc).date()

    for i, exc in enumerate(exceptions):
        dep = exc.get("dependency", "") or f"exception #{i + 1}"
        tag = dep or f"exception #{i + 1}"

        if not exc.get("owner"):
            errors.append(f"{tag}: missing owner")
        if not exc.get("reason"):
            errors.append(f"{tag}: missing reason")
        if not exc.get("expires"):
            errors.append(f"{tag}: missing expiration date")
        else:
            try:
                exp = datetime.fromisoformat(exc["expires"]).date()
                if exp < now:
                    errors.append(f"{tag}: expired on {exc['expires']}")
            except (ValueError, TypeError):
                errors.append(f"{tag}: invalid expires date: {exc['expires']}")
        if not exc.get("created"):
            errors.append(f"{tag}: missing created date")

    if errors:
        print("Validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        return False

    print(f"All {len(exceptions)} exception(s) valid.")
    for exc in exceptions:
        print(
            f"  - {exc['dependency']}: "
            f"owner={exc.get('owner', '?')}, "
            f"expires={exc.get('expires', '?')}"
        )
    return True


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else ".github/dependency-exceptions.yml"
    sys.exit(0 if validate_manifest(path) else 1)
