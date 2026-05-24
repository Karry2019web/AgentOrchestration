"""Agent Runtime — Manages agent process lifecycle with lock protection."""

import os
import signal
import subprocess
import logging
from enum import Enum
from typing import Dict, Optional

from src.common.locks import advisory_lock

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

    def start(self, agent_id: str, command: list, env: Optional[Dict] = None) -> bool:
        if agent_id in self._processes and self._processes[agent_id].poll() is None:
            logger.warning(f"Agent {agent_id} is already running")
            return False

        lock_key = f"agent_runtime:start:{agent_id}"
        try:
            with advisory_lock(lock_key, timeout=5.0):
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
        except Exception:
            return False

    def stop(self, agent_id: str, timeout: int = 10) -> bool:
        proc = self._processes.get(agent_id)
        if not proc or proc.poll() is not None:
            return False

        lock_key = f"agent_runtime:stop:{agent_id}"
        try:
            with advisory_lock(lock_key, timeout=5.0):
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
        except Exception:
            return False

    def get_state(self, agent_id: str) -> RuntimeState:
        proc = self._processes.get(agent_id)
        if proc and proc.poll() is not None:
            self._states[agent_id] = RuntimeState.CRASHED
        return self._states.get(agent_id, RuntimeState.STOPPED)

    def is_running(self, agent_id: str) -> bool:
        proc = self._processes.get(agent_id)
        return proc is not None and proc.poll() is None
