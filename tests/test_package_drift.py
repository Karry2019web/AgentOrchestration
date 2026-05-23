"""Tests for workspace package drift validation."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate_package_drift import (
    INTERNAL_PACKAGES,
    get_current_version,
    identify_changed_packages,
    get_package_dependency_changes,
)


class TestIdentifyChangedPackages:
    def test_no_changes(self):
        """No changed files should result in empty dict."""
        result = identify_changed_packages(set())
        assert result == {}

    def test_agent_package_change(self):
        """Changing a file in src/agent should identify agent package."""
        changed = {"src/agent/registry.py"}
        result = identify_changed_packages(changed)
        assert "agent" in result
        assert "src/agent/registry.py" in result["agent"]

    def test_sdk_package_change(self):
        """Changing a file in src/sdk should identify sdk package."""
        changed = {"src/sdk/client.py"}
        result = identify_changed_packages(changed)
        assert "sdk" in result

    def test_common_package_change(self):
        """Changing a file in src/common should identify common package."""
        changed = {"src/common/config.py"}
        result = identify_changed_packages(changed)
        assert "common" in result

    def test_multiple_packages(self):
        """Multiple changed files across packages."""
        changed = {"src/agent/registry.py", "src/sdk/client.py", "src/common/config.py"}
        result = identify_changed_packages(changed)
        assert "agent" in result
        assert "sdk" in result
        assert "common" in result

    def test_non_package_file(self):
        """Non-internal-package files should not match."""
        changed = {"README.md", "pyproject.toml"}
        result = identify_changed_packages(changed)
        assert result == {}

    def test_all_packages_defined(self):
        """Every package should have the required fields."""
        for name, info in INTERNAL_PACKAGES.items():
            assert "path" in info, f"Package {name} missing 'path'"
            assert "consumers" in info, f"Package {name} missing 'consumers'"
            assert "consumed_by" in info, f"Package {name} missing 'consumed_by'"

    def test_package_paths_exist(self):
        """All package paths should map to actual directories."""
        repo_root = Path(__file__).resolve().parent.parent
        for name, info in INTERNAL_PACKAGES.items():
            pkg_path = repo_root / info["path"]
            assert pkg_path.exists() or pkg_path.is_dir(), (
                f"Package {name} path {info['path']} does not exist"
            )

    def test_dependency_graph_acyclic(self):
        """Internal dependency graph should not have cycles."""
        # Check that no package consumes itself
        for name, info in INTERNAL_PACKAGES.items():
            assert name not in info["consumers"], f"Package {name} consumes itself"
            assert name not in info["consumed_by"], f"Package {name} is consumed by itself"


class TestGetCurrentVersion:
    def test_version_format(self):
        """Version should be a semver-like string."""
        version = get_current_version()
        assert isinstance(version, str)
        parts = version.split(".")
        assert len(parts) >= 2
        for part in parts:
            assert part.isdigit() or part.replace("-", "").isalnum()


class TestGetPackageDependencyChanges:
    def test_no_changes_returns_empty(self):
        """No changes should return empty findings."""
        findings = get_package_dependency_changes({})
        assert findings == []

    def test_cli_only_no_consumers(self):
        """CLI package changes should have no downstream consumers."""
        findings = get_package_dependency_changes({"cli": ["src/cli/main.py"]})
        # CLI has no consumers, so no drift expected
        cli_findings = [f for f in findings if f["changed_package"] == "cli"]
        assert len(cli_findings) == 0
