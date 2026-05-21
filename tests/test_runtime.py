"""Tests for AgentRuntime pipe draining."""

import os
import subprocess as _sp
import sys
import threading
import time

import pytest

from src.agent.runtime import AgentRuntime


class TestAgentRuntimePipeDrain:
    def test_start_drains_stdout(self):
        runtime = AgentRuntime()
        # Start a process that writes to stdout
        cmd = [sys.executable, "-c", "import sys; sys.stdout.write('hello world\n'); sys.stdout.flush()"]
        runtime.start("test-agent", cmd)
        time.sleep(0.2)

        proc = runtime._processes.get("test-agent")
        assert proc is not None
        poll = proc.poll()
        # Process should have completed (short-lived script)
        assert poll is not None or proc.returncode is not None

    def test_start_drains_stderr(self):
        runtime = AgentRuntime()
        cmd = [sys.executable, "-c", "import sys; sys.stderr.write('error output\n'); sys.stderr.flush()"]
        runtime.start("test-agent-2", cmd)
        time.sleep(0.2)

        proc = runtime._processes.get("test-agent-2")
        assert proc is not None

    def test_heavy_output_does_not_hang(self):
        """Write enough to exceed typical pipe buffer (64KB)."""
        runtime = AgentRuntime()
        # Write ~200KB of data
        cmd = [
            sys.executable, "-c",
            "import sys; data = 'x' * 200 * 1024; sys.stdout.write(data); sys.stdout.flush()"
        ]
        runtime.start("test-agent-3", cmd)
        # Should complete within 5 seconds (not hang)
        deadline = time.time() + 5
        proc = runtime._processes.get("test-agent-3")
        while time.time() < deadline and (proc is None or proc.poll() is None):
            time.sleep(0.1)
        assert proc is not None
        assert proc.poll() is not None, "Process hung on large output"

    def test_stop_works_with_drain_threads(self):
        runtime = AgentRuntime()
        cmd = [sys.executable, "-c",
               "import time; [print(i) for i in range(100)]; time.sleep(0.5); print('done')"]
        runtime.start("test-agent-4", cmd)
        time.sleep(0.1)
        # Stop should not hang
        runtime.stop("test-agent-4", timeout=3)
        # Process may have already exited on its own (shorter script)
        # or been stopped — either way, should not be RUNNING
        state = runtime.get_state("test-agent-4").value
        assert state in ("stopped", "crashed")

    def test_concurrent_agents_drain_independently(self):
        runtime = AgentRuntime()
        agents = []
        for i in range(3):
            agent_id = f"test-agent-{i}"
            cmd = [sys.executable, "-c", f"print('agent {i} started')"]
            runtime.start(agent_id, cmd)
            agents.append(agent_id)
        time.sleep(1)
        for agent_id in agents:
            runtime.stop(agent_id, timeout=2)
            state = runtime.get_state(agent_id)
            assert state.value in ("stopped", "crashed")
