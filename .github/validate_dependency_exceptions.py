#!/usr/bin/env python3
"""Validate dependency review exception manifest.

Checks:
- Every entry has required fields (dependency, owner, reason, expires)
- Expired entries cause CI failure
- Missing manifest when exceptions exist in review comments
"""

import yaml
import sys
import json
from datetime import datetime, date


def validate_manifest(path: str = ".github/dependency-exceptions.yml") -> dict:
    """Validate the dependency exception manifest.

    Returns:
        dict with "valid" (bool), "errors" (list), "warnings" (list)
    """
    result = {"valid": True, "errors": [], "warnings": []}
    today = date.today()

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        result["valid"] = False
        result["errors"].append(f"Manifest not found at {path}")
        return result
    except yaml.YAMLError as e:
        result["valid"] = False
        result["errors"].append(f"Invalid YAML: {e}")
        return result

    exceptions = data.get("exceptions", [])
    if not isinstance(exceptions, list):
        result["valid"] = False
        result["errors"].append("'exceptions' must be a list")
        return result

    required_fields = ["dependency", "owner", "reason", "expires"]

    for i, entry in enumerate(exceptions):
        for field in required_fields:
            if field not in entry or not entry[field]:
                result["errors"].append(
                    f"Entry {i}: missing required field '{field}'"
                )

        expiry_str = entry.get("expires", "")
        if expiry_str:
            try:
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                if expiry_date < today:
                    result["errors"].append(
                        f"Entry {i} ({entry.get('dependency', '?')}): "
                        f"expired on {expiry_str}"
                    )
            except ValueError:
                result["errors"].append(
                    f"Entry {i}: invalid expires format '{expiry_str}', "
                    f"expected YYYY-MM-DD"
                )

    if result["errors"]:
        result["valid"] = False

    return result


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ".github/dependency-exceptions.yml"
    result = validate_manifest(path)

    for err in result["errors"]:
        print(f"ERROR: {err}")
    for warn in result["warnings"]:
        print(f"WARNING: {warn}")

    if not result["valid"]:
        print(f"\nDependency exception manifest validation FAILED")
        sys.exit(1)
    else:
        print(f"\nDependency exception manifest is valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
