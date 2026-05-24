"""Agent Runtime — Manages agent process lifecycle and heartbeat guard."""

import os
import signal
import subprocess
import logging
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RuntimeState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


class CompletedState(Enum):
    """Durable terminal states for completed runs."""
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_STATES = frozenset({CompletedState.FINISHED, CompletedState.FAILED, CompletedState.CANCELLED})


class AgentRuntime:
    def __init__(self):
        self._processes: Dict[str, subprocess.Popen] = {}
        self._states: Dict[str, RuntimeState] = {}
        self._completed_runs: Dict[str, CompletedState] = {}
        self._run_owners: Dict[str, str] = {}

    def start(self, agent_id: str, command: list, run_id: Optional[str] = None, env: Optional[Dict] = None) -> bool:
        if agent_id in self._processes and self._processes[agent_id].poll() is None:
            logger.warning(f"Agent {agent_id} is already running")
            return False

        # Guard: refuse to start a new process for a completed run
        if run_id and run_id in self._completed_runs:
            logger.warning(
                f"Refusing to start agent {agent_id} — run {run_id} "
                f"is already in terminal state {self._completed_runs[run_id].value}"
            )
            return False

        self._states[agent_id] = RuntimeState.STARTING
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        process_env["AO_AGENT_ID"] = agent_id
        if run_id:
            process_env["AO_RUN_ID"] = run_id

        try:
            proc = subprocess.Popen(
                command,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._processes[agent_id] = proc
            self._states[agent_id] = RuntimeState.RUNNING
            if run_id:
                self._run_owners[agent_id] = run_id
            logger.info(f"Agent {agent_id} started (PID: {proc.pid})" + (f" for run {run_id}" if run_id else ""))
            return True
        except Exception as e:
            self._states[agent_id] = RuntimeState.CRASHED
            logger.error(f"Failed to start agent {agent_id}: {e}")
            return False

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

        self._states[agent_id] = RuntimeState.STOPPED
        logger.info(f"Agent {agent_id} stopped")
        return True

    def get_state(self, agent_id: str) -> RuntimeState:
        proc = self._processes.get(agent_id)
        if proc and proc.poll() is not None:
            self._states[agent_id] = RuntimeState.CRASHED
        return self._states.get(agent_id, RuntimeState.STOPPED)

    def is_running(self, agent_id: str) -> bool:
        proc = self._processes.get(agent_id)
        return proc is not None and proc.poll() is None

    def process_heartbeat(self, agent_id: str, run_id: str) -> bool:
        """Process a worker heartbeat. Returns True if accepted, False if rejected.

        A heartbeat is rejected when the run is already in a terminal state
        (finished, failed, or cancelled). This prevents worker heartbeats
        from reviving completed runs.
        """
        if run_id in self._completed_runs:
            terminal_state = self._completed_runs[run_id].value
            logger.warning(
                f"Rejecting heartbeat for agent {agent_id} — "
                f"run {run_id} is already {terminal_state}"
            )
            return False

        # Ensure the runtime state reflects that the agent is alive
        if agent_id not in self._states or self._states[agent_id] in (
            RuntimeState.STOPPED, RuntimeState.CRASHED
        ):
            logger.warning(
                f"Rejecting heartbeat for agent {agent_id} — "
                f"agent is in state {self._states.get(agent_id, RuntimeState.STOPPED).value}"
            )
            return False

        return True

    def complete_run(self, agent_id: str, run_id: str, state: CompletedState) -> bool:
        """Mark a run as completed with a durable terminal state.

        Once marked, heartbeats for this run will be rejected.
        """
        if state not in _TERMINAL_STATES:
            logger.error(f"Invalid terminal state {state} for run {run_id}")
            return False

        self._completed_runs[run_id] = state

        # Also update the agent state if needed
        if agent_id in self._run_owners and self._run_owners[agent_id] == run_id:
            self._states[agent_id] = RuntimeState.STOPPED

        logger.info(f"Run {run_id} completed with state {state.value}")
        return True

    def is_run_completed(self, run_id: str) -> bool:
        """Check if a run has been completed (terminal state reached)."""
        return run_id in self._completed_runs

    def get_run_state(self, run_id: str) -> Optional[CompletedState]:
        """Get the terminal state of a completed run, or None if still active."""
        return self._completed_runs.get(run_id)
