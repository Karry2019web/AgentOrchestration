"""Tests for AgentSandbox path resolution and isolation."""

import os
import tempfile
from pathlib import Path
from src.agent.sandbox import AgentSandbox


class TestSandboxPathResolution:
    def test_default_base_path_is_resolved(self):
        """Default temp base_path should be an absolute resolved path."""
        sandbox = AgentSandbox()
        assert sandbox.base_path.is_absolute()
        assert sandbox.base_path == sandbox.base_path.resolve()

    def test_relative_base_path_is_resolved(self):
        """A relative base_path should be resolved to an absolute path."""
        sandbox = AgentSandbox(base_path="relative/sandbox")
        assert sandbox.base_path.is_absolute()
        assert sandbox.base_path.name == "sandbox"
        assert sandbox.base_path.parent.name == "relative"

    def test_absolute_base_path_preserved_after_resolve(self):
        """An already-absolute base_path should remain unchanged after resolve()."""
        with tempfile.TemporaryDirectory() as td:
            sandbox = AgentSandbox(base_path=td)
            assert sandbox.base_path.is_absolute()
            assert sandbox.base_path == Path(td).resolve()

    def test_symlinked_base_path_is_resolved(self):
        """A base_path pointing through a symlink should resolve to the real path."""
        with tempfile.TemporaryDirectory() as td:
            real_dir = Path(td) / "real"
            real_dir.mkdir()
            link_dir = Path(td) / "link"
            link_dir.symlink_to(real_dir, target_is_directory=True)
            sandbox = AgentSandbox(base_path=str(link_dir))
            assert sandbox.base_path == real_dir.resolve()
            assert sandbox.base_path != link_dir

    def test_child_path_inherits_resolved_base(self):
        """Sandbox paths created under a resolved base should also be resolved."""
        with tempfile.TemporaryDirectory() as td:
            sandbox = AgentSandbox(base_path=td)
            child = sandbox.create("test-agent")
            assert child.is_absolute()
            assert str(child).startswith(str(sandbox.base_path))
            assert sandbox.base_path in child.parents

    def test_dotted_relative_path_resolved_correctly(self):
        """A relative path with '..' segments should be resolved to a canonical path."""
        with tempfile.TemporaryDirectory() as td:
            sandbox = AgentSandbox(base_path=os.path.join(td, "..", os.path.basename(td), "sub"))
            assert sandbox.base_path.is_absolute()
            assert sandbox.base_path.name == "sub"
            assert sandbox.base_path.parent == Path(td).resolve()

    def test_empty_base_path_falls_back_to_tempdir(self):
        """Passing an empty string base_path should fall back to a temp directory."""
        sandbox = AgentSandbox(base_path="")
        assert sandbox.base_path.is_absolute()
        assert sandbox.base_path.name.startswith("ao_sandbox_")
