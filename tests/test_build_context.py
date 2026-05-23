"""Tests for Docker build context audit."""

import pytest
from pathlib import Path
from src.common.build_context import (
    audit_context,
    scan_context,
    PROHIBITED_DIRECTORIES,
    DEFAULT_CONTEXT_BUDGET,
)


class TestBuildContext:
    def test_clean_directory_passes(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("print('hello')")
        (tmp_path / "README.md").write_text("# test")
        assert len(audit_context(tmp_path)) == 0

    def test_reports_prohibited_node_modules(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep").write_text("{}")
        issues = audit_context(tmp_path)
        prohibited = [i for i in issues if i[2] == "prohibited_directory"]
        assert any("node_modules" in i[0] for i in prohibited)

    def test_reports_prohibited_venv(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "bin" / "python").write_text("fake")
        issues = audit_context(tmp_path)
        prohibited = [i for i in issues if i[2] == "prohibited_directory"]
        assert any(".venv" in i[0] for i in prohibited)

    def test_reports_prohibited_pycache(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "module.cpython-311.pyc").write_text("fake")
        issues = audit_context(tmp_path)
        prohibited = [i for i in issues if i[2] == "prohibited_directory"]
        assert any("__pycache__" in i[0] for i in prohibited)

    def test_large_context_triggers_budget(self, tmp_path):
        data = b"x" * (DEFAULT_CONTEXT_BUDGET + 1)
        (tmp_path / "large_file.bin").write_bytes(data)
        issues = audit_context(tmp_path)
        over_budget = [i for i in issues if "over_budget" in i[2]]
        assert len(over_budget) > 0

    def test_scan_reports_total_size(self, tmp_path):
        half = DEFAULT_CONTEXT_BUDGET // 2 + 1
        (tmp_path / "a.bin").write_bytes(b"x" * half)
        (tmp_path / "b.bin").write_bytes(b"x" * half)
        issues = scan_context(tmp_path)
        totals = [i for i in issues if i[0] == "(total)"]
        assert len(totals) > 0
        assert totals[0][1] >= DEFAULT_CONTEXT_BUDGET

    def test_prohibited_directories_listed(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        for i in range(5):
            (tmp_path / "node_modules" / f"pkg{i}").write_text("x" * 1024 * 1024)
        issues = scan_context(tmp_path)
        prohibited = [i for i in issues if i[2] == "prohibited_directory"]
        assert len(prohibited) >= 1

    def test_custom_budget(self, tmp_path):
        custom_budget = 100
        (tmp_path / "small.bin").write_bytes(b"x" * 500)
        issues = audit_context(tmp_path, budget=custom_budget)
        over_budget = [i for i in issues if "over_budget" in i[2]]
        assert len(over_budget) > 0
