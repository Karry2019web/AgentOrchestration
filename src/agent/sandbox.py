"""Agent Sandbox — Isolated execution environment for agents."""

import os
import tempfile
import resource
from pathlib import Path
from typing import Dict, Optional


class ResourceLimits:
    def __init__(self, cpu_time: int = 60, memory_mb: int = 512, disk_mb: int = 100):
        self.cpu_time = cpu_time
        self.memory_mb = memory_mb
        self.disk_mb = disk_mb


class SandboxContainmentError(RuntimeError):
    """Raised when a sandbox path falls outside the allowed base path."""


class AgentSandbox:
    def __init__(self, base_path: Optional[str] = None):
        root = base_path or tempfile.mkdtemp(prefix="ao_sandbox_")
        self.base_path = Path(root).resolve()
        self._sandboxes: Dict[str, Path] = {}

    def create(self, agent_id: str, limits: Optional[ResourceLimits] = None) -> Path:
        sandbox_path = (self.base_path / agent_id).resolve()
        if not self._is_contained(sandbox_path):
            raise SandboxContainmentError(
                f"Cannot create sandbox at {sandbox_path}: outside base path {self.base_path}"
            )
        sandbox_path.mkdir(parents=True, exist_ok=True)
        self._sandboxes[agent_id] = sandbox_path
        return sandbox_path

    def destroy(self, agent_id: str) -> bool:
        sandbox = self._sandboxes.pop(agent_id, None)
        if not sandbox:
            return False

        resolved = sandbox.resolve()
        if not self._is_contained(resolved):
            return False

        if resolved.exists():
            import shutil
            shutil.rmtree(resolved, ignore_errors=True)
            return True
        return False

    def _is_contained(self, sandbox_path: Path) -> bool:
        try:
            sandbox_path.relative_to(self.base_path)
            return True
        except ValueError:
            return False

    def get_path(self, agent_id: str) -> Optional[Path]:
        return self._sandboxes.get(agent_id)

    def apply_limits(self, agent_id: str, limits: ResourceLimits) -> None:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_time, limits.cpu_time))
            mem_bytes = limits.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, resource.error):
            pass

    def cleanup_all(self) -> None:
        for agent_id in list(self._sandboxes.keys()):
            self.destroy(agent_id)
