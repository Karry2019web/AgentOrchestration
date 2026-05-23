"""Agent Runtime — Manages agent process lifecycle."""

import os
import signal
import subprocess
import logging
import time
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RuntimeState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


class AgentRuntime:
    def __init__(self):
        self._processes: Dict[str, subprocess.Popen] = {}
        self._states: Dict[str, RuntimeState] = {}
        self._child_processes: Dict[str, List[subprocess.Popen]] = {}
        self._run_timeout: int = 300

    def start(self, agent_id: str, command: list, env: Optional[Dict] = None) -> bool:
        if agent_id in self._processes and self._processes[agent_id].poll() is None:
            logger.warning(f"Agent {agent_id} is already running")
            return False

        self._states[agent_id] = RuntimeState.STARTING
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        process_env["AO_AGENT_ID"] = agent_id

        try:
            proc = subprocess.Popen(
                command,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._processes[agent_id] = proc
            self._child_processes[agent_id] = []
            self._states[agent_id] = RuntimeState.RUNNING
            logger.info(f"Agent {agent_id} started (PID: {proc.pid})")
            return True
        except Exception as e:
            self._states[agent_id] = RuntimeState.CRASHED
            logger.error(f"Failed to start agent {agent_id}: {e}")
            return False

    def track_child(self, agent_id: str, proc: subprocess.Popen) -> None:
        """Track a child subprocess spawned by this agent."""
        if agent_id not in self._child_processes:
            self._child_processes[agent_id] = []
        self._child_processes[agent_id].append(proc)
        logger.debug(f"Tracking child PID {proc.pid} for agent {agent_id}")

    def stop(self, agent_id: str, timeout: int = 10) -> bool:
        proc = self._processes.get(agent_id)
        if not proc or proc.poll() is not None:
            return False

        self._states[agent_id] = RuntimeState.STOPPING
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        self._cleanup_orphans(agent_id)
        self._states[agent_id] = RuntimeState.STOPPED
        logger.info(f"Agent {agent_id} stopped")
        return True

    def cancel_orphaned_subprocesses(self, agent_id: str) -> int:
        """Cancel all orphaned child subprocesses for a given agent.
        Returns the number of processes killed."""
        count = 0
        children = self._child_processes.get(agent_id, [])
        for child in children:
            if child.poll() is None:
                try:
                    child.send_signal(signal.SIGTERM)
                    child.wait(timeout=5)
                    count += 1
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to kill child {child.pid}: {e}")
        self._child_processes[agent_id] = [c for c in children if c.poll() is None]
        return count

    def _cleanup_orphans(self, agent_id: str) -> None:
        """Internal cleanup of orphaned child processes."""
        self.cancel_orphaned_subprocesses(agent_id)
        if agent_id in self._child_processes:
            del self._child_processes[agent_id]

    def get_child_count(self, agent_id: str) -> int:
        """Return number of tracked child processes still running."""
        return len([c for c in self._child_processes.get(agent_id, []) if c.poll() is None])

    def get_state(self, agent_id: str) -> RuntimeState:
        proc = self._processes.get(agent_id)
        if proc and proc.poll() is not None:
            self._states[agent_id] = RuntimeState.CRASHED
        return self._states.get(agent_id, RuntimeState.STOPPED)

    def is_running(self, agent_id: str) -> bool:
        proc = self._processes.get(agent_id)
        return proc is not None and proc.poll() is None

    def set_run_timeout(self, timeout_seconds: int) -> None:
        """Set the default run timeout for agent processes."""
        self._run_timeout = timeout_seconds
