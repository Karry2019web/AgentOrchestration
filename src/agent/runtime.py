"""Agent Runtime — Manages agent process lifecycle."""

import os
import signal
import subprocess
import logging
from enum import Enum
from typing import Dict, Optional

from .model_routing_guard import ModelRoutingGuard, ModelMode, RoutingDecision

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
        self._routing_guard = ModelRoutingGuard()

    @property
    def routing_guard(self) -> ModelRoutingGuard:
        return self._routing_guard

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

    def route_to_model(
        self, agent_id: str, target_mode: str, fallback_chain: Optional[list] = None
    ) -> bool:
        """Route an agent's execution to the specified model mode.

        Uses ModelRoutingGuard to validate the target mode before allowing
        any side effects (process start, state mutation, etc.).

        Returns True if routing was successful, False if the mode is unsupported.
        """
        route_id = f"{agent_id}:{target_mode}"
        try:
            model_mode = ModelMode(target_mode)
        except ValueError:
            logger.error(f"Unknown model mode: {target_mode}")
            return False

        # Build fallback chain if provided
        fallback_modes = None
        if fallback_chain:
            fallback_modes = []
            for mode_str in fallback_chain:
                try:
                    fallback_modes.append(ModelMode(mode_str))
                except ValueError:
                    logger.warning(f"Unknown fallback mode: {mode_str}")

        decision = self._routing_guard.check_fallback(
            route_id, model_mode, fallback_modes
        )

        if not decision.allowed:
            logger.warning(
                f"Routing blocked for agent {agent_id}: {decision.reason}"
            )
            return False

        # Record the routing attempt — retries are bounded and idempotent
        self._routing_guard.record_routing(route_id, model_mode, attempt=1)
        logger.info(
            f"Agent {agent_id} routed to {target_mode} (route_id={route_id})"
        )
        return True