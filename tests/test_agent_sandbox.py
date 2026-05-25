from pathlib import Path

from src.agent.sandbox import AgentSandbox, SandboxContainmentError


def test_destroy_removes_contained_sandbox(tmp_path):
    sandbox = AgentSandbox(base_path=str(tmp_path / "base"))
    created = sandbox.create("agent-a")
    marker = created / "marker.txt"
    marker.write_text("owned")

    assert sandbox.destroy("agent-a")
    assert not created.exists()


def test_destroy_rejects_tracked_path_outside_base(tmp_path):
    base = tmp_path / "base"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("do not remove")

    sandbox = AgentSandbox(base_path=str(base))
    sandbox._sandboxes["agent-a"] = outside

    assert not sandbox.destroy("agent-a")
    assert outside.exists()
    assert marker.read_text() == "do not remove"
    assert sandbox.get_path("agent-a") is None


def test_destroy_rejects_symlink_escape_from_base(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("do not remove")
    link = base / "agent-a"
    link.symlink_to(outside, target_is_directory=True)

    sandbox = AgentSandbox(base_path=str(base))
    sandbox._sandboxes["agent-a"] = Path(link)

    assert not sandbox.destroy("agent-a")
    assert outside.exists()
    assert marker.read_text() == "do not remove"


def test_create_inside_base_is_accepted(tmp_path):
    sandbox = AgentSandbox(base_path=str(tmp_path / "base"))
    path = sandbox.create("agent-b")
    assert path.exists()
    assert str(path.resolve()).startswith(str((tmp_path / "base").resolve()))


def test_base_path_is_resolved(tmp_path):
    base = tmp_path / "base" / ".." / "base"
    sandbox = AgentSandbox(base_path=str(base))
    assert not sandbox.base_path.as_posix().endswith("..")
    assert sandbox.base_path == (tmp_path / "base").resolve()


def test_destroy_nonexistent_agent_returns_false(tmp_path):
    sandbox = AgentSandbox(base_path=str(tmp_path / "base"))
    assert not sandbox.destroy("no-such-agent")
