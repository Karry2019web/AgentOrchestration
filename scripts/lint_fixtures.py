#!/usr/bin/env python3
"""Fixture linting — validate that test data uses synthetic content.

Scans test files under tests/ for prohibited patterns that indicate
real-world samples (IP addresses, emails, secrets, realistic PII).

Passes if no violations are found.
Fails with exit code 1 and lists violations otherwise.
"""

import ast
import os
import re
import sys


PROHIBITED_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\\b\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b", "Raw IP address"),
    (r"(?i)\\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}\\b", "Email address"),
    (r"(?i)(password|secret|token|apikey|api_key)\\s*[:=]\\s*['"][^'"]+['"]", "Hardcoded credential"),
    (r"(?i)(ssn|social.security|credit.card|phone.number)", "PII reference in fixture"),
    (r"(?i)AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"(?i)-----BEGIN (RSA |EC )?PRIVATE KEY-----", "Private key material"),
]

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv"}
SKIP_FILES = {"lint_fixtures.py", "synthetic_fixtures.py"}

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _is_approved_fixture(path: str) -> bool:
    rel = os.path.relpath(path, BASE_DIR)
    return rel.startswith("tests/data/") and rel.endswith("synthetic_fixtures.py")


def check_file(path: str) -> list[str]:
    violations: list[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        return [f"  [IO ERROR] {path}: {exc}"]

    for lineno, line in enumerate(lines, 1):
        for pattern, label in PROHIBITED_PATTERNS:
            if re.search(pattern, line):
                violations.append(
                    f"  [{label}] {path}:{lineno}: {line.rstrip()[:120]}"
                )
    return violations


def main() -> int:
    test_dir = os.path.join(BASE_DIR, "tests")
    if not os.path.isdir(test_dir):
        print("No tests/ directory found — skipping fixture lint.")
        return 0

    all_violations: list[str] = []

    for root, dirs, files in os.walk(test_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            if fname in SKIP_FILES:
                continue
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            if _is_approved_fixture(fpath):
                continue
            all_violations.extend(check_file(fpath))

    if all_violations:
        print(f"[FAIL] Found {len(all_violations)} fixture violation(s):\n")
        for v in all_violations:
            print(v)
        print(
            "\n"
            "All test fixture data must be synthetic. Use tests/data/synthetic_fixtures.py "
            "for approved fixture helpers or replace hardcoded real-looking data with "
            "programmatically generated test values."
        )
        return 1

    print("[PASS] All test fixtures use synthetic data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
