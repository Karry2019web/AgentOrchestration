"""Agent Runtime — Manages agent process lifecycle with state-machine guards,
durable failure recording, and bounded idempotent retries."""

import os
import signal
import subprocess
import logging
import time
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


class RuntimeState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


class RuntimeTransition(Enum):
    """Legal state-machine transitions."""
    STOPPED_TO_STARTING = ("stopped", "starting")
    STARTING_TO_RUNNING = ("starting", "running")
    STARTING_TO_CRASHED = ("starting", "crashed")
    RUNNING_TO_STOPPING = ("running", "stopping")
    STOPPING_TO_STOPPED = ("stopping", "stopped")
    STOPPING_TO_CRASHED = ("stopping", "crashed")
    CRASHED_TO_STARTING = ("crashed", "starting")
    STOPPED_TO_CRASHED = ("stopped", "crashed")

    def __init__(self, from_state: str, to_state: str):
        self.from_state = from_state
        self.to_state = to_state

    @classmethod
    def is_legal(cls, current: RuntimeState, target: RuntimeState) -> bool:
        pair = (current.value, target.value)
        return any(t.from_state == pair[0] and t.to_state == pair[1] for t in cls)


@dataclass
class RuntimeFailure:
    """Durable record of why an agent stopped or failed."""
    agent_id: str
    reason: str
    timestamp: float
    exit_code: Optional[int] = None
    transition: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "exit_code": self.exit_code,
            "transition": self.transition,
        }


MAX_RETRY_COUNT = 3


class AgentRuntime:
    def __init__(self):
        self._processes: Dict[str, subprocess.Popen] = {}
        self._states: Dict[str, RuntimeState] = {}
        self._failures: Dict[str, List[RuntimeFailure]] = {}
        self._retry_counts: Dict[str, int] = {}
        self._durable_state: Dict[str, dict] = {}

    def _transition(self, agent_id: str, target: RuntimeState) -> bool:
        """State-machine guard: only allow legal transitions."""
        current = self._states.get(agent_id, RuntimeState.STOPPED)
        if not RuntimeTransition.is_legal(current, target):
            logger.warning(
                f"Illegal state transition for agent {agent_id}: "
                f"{current.value} -> {target.value}"
            )
            return False
        self._states[agent_id] = target
        return True

    def _persist_durable_state(self, agent_id: str) -> None:
        """Persist durable state before emitting side effects."""
        current_state = self._states.get(agent_id, RuntimeState.STOPPED)
        proc = self._processes.get(agent_id)
        exit_code = proc.poll() if proc else None
        self._durable_state[agent_id] = {
            "agent_id": agent_id,
            "state": current_state.value,
            "exit_code": exit_code,
            "recorded_at": time.time(),
        }

    def _record_failure_before_shutdown(
        self, agent_id: str, reason: str, exit_code: Optional[int] = None
    ) -> None:
        """Record failure reason BEFORE worker shutdown / state mutation."""
        failure = RuntimeFailure(
            agent_id=agent_id,
            reason=reason,
            timestamp=time.time(),
            exit_code=exit_code,
            transition=self._states.get(agent_id, RuntimeState.STOPPED).value,
        )
        if agent_id not in self._failures:
            self._failures[agent_id] = []
        self._failures[agent_id].append(failure)
        self._persist_durable_state(agent_id)
        logger.info(
            f"Recorded failure for agent {agent_id}: {reason} "
            f"(exit_code={exit_code})"
        )

    def start(
        self, agent_id: str, command: list, env: Optional[Dict] = None
    ) -> bool:
        current = self._states.get(agent_id, RuntimeState.STOPPED)
        if current in (RuntimeState.STARTING, RuntimeState.STOPPING):
            logger.warning(
                f"Agent {agent_id} is in transitional state {current.value}, cannot start"
            )
            return False
        if agent_id in self._retry_counts:
            if self._retry_counts[agent_id] >= MAX_RETRY_COUNT:
                self._record_failure_before_shutdown(
                    agent_id, f"Max retries ({MAX_RETRY_COUNT}) exceeded"
                )
                return False
        if not self._transition(agent_id, RuntimeState.STARTING):
            return False
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
            self._persist_durable_state(agent_id)
            self._transition(agent_id, RuntimeState.RUNNING)
            logger.info(f"Agent {agent_id} started (PID: {proc.pid})")
            return True
        except Exception as e:
            reason = f"Failed to start agent {agent_id}: {e}"
            self._record_failure_before_shutdown(agent_id, reason)
            self._transition(agent_id, RuntimeState.CRASHED)
            logger.error(reason)
            return False

    def stop(self, agent_id: str, timeout: int = 10) -> bool:
        proc = self._processes.get(agent_id)
        if not proc or proc.poll() is not None:
            return False
        current = self._states.get(agent_id, RuntimeState.STOPPED)
        if current == RuntimeState.STOPPING:
            logger.warning(f"Agent {agent_id} is already stopping")
            return False
        if not self._transition(agent_id, RuntimeState.STOPPING):
            return False
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            reason = f"Agent {agent_id} did not stop within {timeout}s, sending SIGKILL"
            self._record_failure_before_shutdown(agent_id, reason, exit_code=None)
            proc.kill()
            proc.wait()
        exit_code = proc.returncode
        if exit_code is not None and exit_code != 0:
            self._record_failure_before_shutdown(
                agent_id, f"Process exited with code {exit_code}", exit_code=exit_code
            )
        else:
            self._persist_durable_state(agent_id)
        self._transition(agent_id, RuntimeState.STOPPED)
        logger.info(f"Agent {agent_id} stopped (exit_code={exit_code})")
        return True

    def get_state(self, agent_id: str) -> RuntimeState:
        proc = self._processes.get(agent_id)
        current = self._states.get(agent_id, RuntimeState.STOPPED)
        if proc and proc.poll() is not None and current == RuntimeState.RUNNING:
            exit_code = proc.returncode
            self._record_failure_before_shutdown(
                agent_id, f"Process crashed unexpectedly (exit_code={exit_code})", exit_code=exit_code
            )
            self._transition(agent_id, RuntimeState.CRASHED)
            return RuntimeState.CRASHED
        return current

    def is_running(self, agent_id: str) -> bool:
        state = self.get_state(agent_id)
        return state in (RuntimeState.RUNNING, RuntimeState.STARTING)

    def get_failures(self, agent_id: str) -> List[RuntimeFailure]:
        return list(self._failures.get(agent_id, []))

    def get_last_failure(self, agent_id: str) -> Optional[RuntimeFailure]:
        failures = self._failures.get(agent_id, [])
        return failures[-1] if failures else None

    def get_durable_state(self, agent_id: str) -> Optional[dict]:
        return self._durable_state.get(agent_id)

    def get_retry_count(self, agent_id: str) -> int:
        return self._retry_counts.get(agent_id, 0)

    def reset_retries(self, agent_id: str) -> None:
        self._retry_counts.pop(agent_id, None)

    def clear_failures(self, agent_id: str) -> None:
        self._failures.pop(agent_id, None)

    def shutdown_all(self) -> None:
        for agent_id in list(self._processes.keys()):
            try:
                self.stop(agent_id)
            except Exception as e:
                self._record_failure_before_shutdown(
                    agent_id, f"Error during global shutdown: {e}"
                )
