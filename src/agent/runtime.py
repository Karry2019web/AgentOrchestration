"""Agent Runtime — Manages agent process lifecycle and trace aggregation."""

import os
import signal
import subprocess
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from src.common.trace import TraceAggregator, DEFAULT_MEMORY_LIMIT_BYTES

logger = logging.getLogger(__name__)


class RuntimeState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


class AgentRuntime:
    def __init__(self, trace_memory_limit: int = DEFAULT_MEMORY_LIMIT_BYTES):
        self._processes: Dict[str, subprocess.Popen] = {}
        self._states: Dict[str, RuntimeState] = {}
        self._trace = TraceAggregator(memory_limit_bytes=trace_memory_limit)
        self._trace_enabled = True

    @property
    def trace_aggregator(self) -> TraceAggregator:
        return self._trace

    @property
    def trace_enabled(self) -> bool:
        return self._trace_enabled

    def enable_trace(self) -> None:
        self._trace_enabled = True

    def disable_trace(self) -> None:
        self._trace_enabled = False

    def _record_trace(self, agent_id: str, event: str, payload: Optional[Dict] = None) -> None:
        """Record a trace event if tracing is enabled and memory permits."""
        if not self._trace_enabled:
            return
        trace_id = f"rt_{agent_id}_{int(__import__('time').time() * 1000)}"
        accepted = self._trace.record(trace_id, agent_id, event, payload)
        if not accepted:
            logger.warning(
                "Trace memory limit reached for %s — event '%s' dropped",
                agent_id, event,
            )

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
            self._record_trace(agent_id, "agent.started", {"pid": proc.pid})
            logger.info(f"Agent {agent_id} started (PID: {proc.pid})")
            return True
        except Exception as e:
            self._states[agent_id] = RuntimeState.CRASHED
            self._record_trace(agent_id, "agent.start_failed", {"error": str(e)})
            logger.error(f"Failed to start agent {agent_id}: {e}")
            return False

    def stop(self, agent_id: str, timeout: int = 10) -> bool:
        proc = self._processes.get(agent_id)
        if not proc or proc.poll() is not None:
            return False

        self._states[agent_id] = RuntimeState.STOPPING
        self._record_trace(agent_id, "agent.stopping", {"timeout": timeout})
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        self._states[agent_id] = RuntimeState.STOPPED
        self._record_trace(agent_id, "agent.stopped", {})
        logger.info(f"Agent {agent_id} stopped")
        return True

    def get_state(self, agent_id: str) -> RuntimeState:
        proc = self._processes.get(agent_id)
        if proc and proc.poll() is not None:
            self._states[agent_id] = RuntimeState.CRASHED
            self._record_trace(agent_id, "agent.crashed", {"exit_code": proc.returncode})
        return self._states.get(agent_id, RuntimeState.STOPPED)

    def is_running(self, agent_id: str) -> bool:
        proc = self._processes.get(agent_id)
        return proc is not None and proc.poll() is None

    def get_trace_snapshot(self) -> Dict[str, Any]:
        """Return current trace aggregation state for monitoring."""
        return self._trace.snapshot()

    def flush_traces(self) -> List[Dict[str, Any]]:
        """Return and clear buffered trace entries."""
        return self._trace.flush()

# 2026-05-23T09:50:00 update
