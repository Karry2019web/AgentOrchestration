"""Agent Sandbox — Isolated execution environment for agents."""

import os
import tempfile
import resource
from typing import Dict, Optional
from pathlib import Path


class ResourceLimits:
    """Resource constraints for a sandboxed agent.

    Attributes:
        cpu_time: Maximum CPU time in seconds (soft limit).
        memory_mb: Maximum virtual memory (address space) in MB.
        disk_mb: Maximum file size any single process can write, in MB.
            Enforced via RLIMIT_FSIZE. A value of 0 forbids file writes entirely.
    """

    def __init__(self, cpu_time: int = 60, memory_mb: int = 512, disk_mb: int = 100):
        self.cpu_time = cpu_time
        self.memory_mb = memory_mb
        self.disk_mb = disk_mb


class AgentSandbox:
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or tempfile.mkdtemp(prefix="ao_sandbox_"))

    def create(self, agent_id: str, limits: Optional[ResourceLimits] = None) -> Path:
        sandbox_path = self.base_path / agent_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        self._sandboxes[agent_id] = sandbox_path
        if limits:
            self.apply_limits(agent_id, limits)
        return sandbox_path

    def destroy(self, agent_id: str) -> bool:
        sandbox = self._sandboxes.pop(agent_id, None)
        if sandbox and sandbox.exists():
            import shutil
            shutil.rmtree(sandbox, ignore_errors=True)
            return True
        return False

    def get_path(self, agent_id: str) -> Optional[Path]:
        return self._sandboxes.get(agent_id)

    def apply_limits(self, agent_id: str, limits: ResourceLimits) -> None:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_time, limits.cpu_time))
            mem_bytes = limits.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            # Enforce disk quota via maximum file size
            disk_bytes = limits.disk_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (disk_bytes, disk_bytes))
        except (ValueError, resource.error) as e:
            pass

    def cleanup_all(self) -> None:
        for agent_id in list(self._sandboxes.keys()):
            self.destroy(agent_id)
