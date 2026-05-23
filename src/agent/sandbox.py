"""Agent Sandbox — Isolated execution environment for agents."""

import os
import re
import tempfile
import resource
from typing import Dict, Optional
from pathlib import Path


class ResourceLimits:
    def __init__(self, cpu_time: int = 60, memory_mb: int = 512, disk_mb: int = 100):
        self.cpu_time = cpu_time
        self.memory_mb = memory_mb
        self.disk_mb = disk_mb


class AgentSandbox:
    _UNSAFE_PATTERN = re.compile(r"[/\\]|\.\.|\0")

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or tempfile.mkdtemp(prefix="ao_sandbox_"))
        self._sandboxes: Dict[str, Path] = {}

    def _sanitize_agent_id(self, agent_id: str) -> str:
        if not agent_id or not isinstance(agent_id, str):
            raise ValueError(f"Invalid agent_id: must be a non-empty string, got {type(agent_id).__name__}")
        if self._UNSAFE_PATTERN.search(agent_id):
            raise ValueError(
                f"Invalid agent_id {agent_id!r}: contains path separators, "
                f"parent-directory segments, or null bytes"
            )
        return agent_id

    def create(self, agent_id: str, limits: Optional[ResourceLimits] = None) -> Path:
        safe_id = self._sanitize_agent_id(agent_id)
        sandbox_path = (self.base_path / safe_id).resolve()
        # Verify resolved path stays under base_path
        try:
            sandbox_path.relative_to(self.base_path.resolve())
        except ValueError:
            raise ValueError(
                f"Resolved sandbox path {sandbox_path} is outside base path {self.base_path}"
            )
        sandbox_path.mkdir(parents=True, exist_ok=True)
        self._sandboxes[agent_id] = sandbox_path
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
        except (ValueError, resource.error) as e:
            pass

    def cleanup_all(self) -> None:
        for agent_id in list(self._sandboxes.keys()):
            self.destroy(agent_id)
