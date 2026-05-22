"""Tests for Agent Runtime heartbeat / state machine guards."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent.runtime import AgentRuntime, RuntimeState


def test_get_state_returns_stopped_for_unknown():
    runtime = AgentRuntime()
    assert runtime.get_state("unknown") == RuntimeState.STOPPED


def test_start_refuses_after_set_run_completed():
    runtime = AgentRuntime()
    runtime.set_run_completed("agent-1")
    result = runtime.start("agent-1", ["echo", "hi"])
    assert result is False


def test_get_state_preserves_terminal():
    runtime = AgentRuntime()
    runtime.set_run_completed("agent-1")
    state = runtime.get_state("agent-1")
    assert state == RuntimeState.STOPPED


def test_set_run_completed_makes_not_running():
    runtime = AgentRuntime()
    runtime.set_run_completed("agent-1")
    assert runtime.is_running("agent-1") is False


def test_is_terminal_recognizes_stopped():
    runtime = AgentRuntime()
    assert runtime._is_terminal(RuntimeState.STOPPED) is True
    assert runtime._is_terminal(RuntimeState.CRASHED) is True


def test_is_terminal_rejects_active():
    runtime = AgentRuntime()
    assert runtime._is_terminal(RuntimeState.RUNNING) is False
    assert runtime._is_terminal(RuntimeState.STARTING) is False
    assert runtime._is_terminal(RuntimeState.STOPPING) is False
