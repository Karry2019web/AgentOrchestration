"""Agent Runtime — Manages agent process lifecycle with durable state guards."""

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


class ResultState(Enum):
    """Durable terminal states for tool results processing."""
    PENDING = "pending"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    FINALIZED = "finalized"


class AgentRuntime:
    """Runtime manager with durable state-machine guards for tool results."""

    def __init__(self):
        self._processes: Dict[str, subprocess.Popen] = {}
        self._states: Dict[str, RuntimeState] = {}
        # Durable result state tracking — each agent has exactly one terminal outcome
        self._result_states: Dict[str, ResultState] = {}
        self._terminal_outcomes: Dict[str, bool] = {}

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
            self._states[agent_id] = RuntimeState.RUNNING
            logger.info(f"Agent {agent_id} started (PID: {proc.pid})")
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

    # --- Durable state-machine guard for tool results ---

    def record_result_state(self, agent_id: str, state: ResultState) -> bool:
        """Record a durable terminal outcome for an agent's result.
        
        Returns True if the state was recorded, False if already finalized.
        This guard ensures exactly one terminal outcome per agent.
        """
        if self._terminal_outcomes.get(agent_id, False):
            logger.warning(f"Agent {agent_id} already has a terminal outcome — ignoring duplicate")
            return False
        self._result_states[agent_id] = state
        self._terminal_outcomes[agent_id] = True
        logger.info(f"Agent {agent_id} result state: {state.value}")
        return True

    def get_result_state(self, agent_id: str) -> ResultState:
        return self._result_states.get(agent_id, ResultState.PENDING)

    def has_terminal_outcome(self, agent_id: str) -> bool:
        return self._terminal_outcomes.get(agent_id, False)

    def reset_result_state(self, agent_id: str) -> None:
        """Reset result state for a fresh execution."""
        self._result_states.pop(agent_id, None)
        self._terminal_outcomes.pop(agent_id, None)
