"""Tests for agent runtime state transitions."""

import sys
import importlib.util

spec = importlib.util.spec_from_file_location(
    "runtime",
    "src/agent/runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

AgentRuntime = runtime.AgentRuntime
RuntimeState = runtime.RuntimeState


def test_get_state_returns_stopped_for_unknown_agent():
    runtime_inst = AgentRuntime()
    assert runtime_inst.get_state("nonexistent") == RuntimeState.STOPPED


def test_get_state_returns_running_for_active_process():
    runtime_inst = AgentRuntime()
    runtime_inst.start("sleeper", [sys.executable, "-c", "import time; time.sleep(30)"])
    assert runtime_inst.get_state("sleeper") == RuntimeState.RUNNING
    runtime_inst.stop("sleeper", timeout=5)


def test_get_state_returns_stopped_on_zero_exit():
    runtime_inst = AgentRuntime()
    runtime_inst.start("exiter-ok", [sys.executable, "-c", "import sys; sys.exit(0)"])
    proc = runtime_inst._processes["exiter-ok"]
    proc.wait(timeout=10)
    assert runtime_inst.get_state("exiter-ok") == RuntimeState.STOPPED


def test_get_state_returns_crashed_on_nonzero_exit():
    runtime_inst = AgentRuntime()
    runtime_inst.start("exiter-fail", [sys.executable, "-c", "import sys; sys.exit(42)"])
    proc = runtime_inst._processes["exiter-fail"]
    proc.wait(timeout=10)
    assert runtime_inst.get_state("exiter-fail") == RuntimeState.CRASHED


def test_get_state_not_affected_by_process_running():
    runtime_inst = AgentRuntime()
    runtime_inst.start("runner", [sys.executable, "-c", "import time; time.sleep(30)"])
    proc = runtime_inst._processes["runner"]
    assert proc.poll() is None
    assert runtime_inst.get_state("runner") == RuntimeState.RUNNING
    runtime_inst.stop("runner", timeout=5)
