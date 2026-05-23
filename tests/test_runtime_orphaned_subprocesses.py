"""Tests for runtime orphaned subprocess cancellation."""
import subprocess
import sys
import time
from src.agent.runtime import AgentRuntime


class TestRuntimeOrphanedSubprocesses:
    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_track_child(self):
        """Track a child subprocess and verify it is registered."""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.runtime.track_child("test-agent", proc)
        assert self.runtime.get_child_count("test-agent") == 1
        proc.kill()
        proc.wait()

    def test_cancel_orphaned_subprocesses(self):
        """Cancel orphaned subprocesses and verify they are killed."""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.runtime.track_child("test-agent", proc)
        assert self.runtime.get_child_count("test-agent") == 1

        count = self.runtime.cancel_orphaned_subprocesses("test-agent")
        assert count == 1
        assert proc.poll() is not None

    def test_cancel_already_dead_child(self):
        """Cancelling an already-exited child should not raise."""
        proc = subprocess.Popen([sys.executable, "-c", "pass"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.wait()
        self.runtime.track_child("test-agent", proc)
        count = self.runtime.cancel_orphaned_subprocesses("test-agent")
        assert count == 0

    def test_stop_cleans_up_orphans(self):
        """Stopping an agent should also clean up its orphaned children."""
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        agent = subprocess.Popen([sys.executable, "-c",
                                  "import time; time.sleep(5)"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.runtime._processes["test-agent"] = agent
        self.runtime._child_processes["test-agent"] = [child]

        self.runtime.stop("test-agent", timeout=3)
        assert child.poll() is not None, "child should be killed on agent stop"
        assert agent.poll() is not None, "agent should be stopped"
