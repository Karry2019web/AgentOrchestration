"""Agent Sandbox — Isolated execution environment for agents."""

import os
import tempfile
import resource
import re
from typing import Dict, Optional
from pathlib import Path


class ResourceLimits:
    def __init__(self, cpu_time: int = 60, memory_mb: int = 512, disk_mb: int = 100):
        self.cpu_time = cpu_time
        self.memory_mb = memory_mb
        self.disk_mb = disk_mb


class AgentSandbox:
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or tempfile.mkdtemp(prefix="ao_sandbox_")).resolve()
        self._sandboxes: Dict[str, Path] = {}

    def create(self, agent_id: str, limits: Optional[ResourceLimits] = None) -> Path:
        self._validate_agent_id(agent_id)
        sandbox_path = (self.base_path / agent_id).resolve()
        if not str(sandbox_path).startswith(str(self.base_path)):
            raise ValueError(
                f"Agent ID '{agent_id}' resolves to a path outside the sandbox base directory"
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

    @staticmethod
    def _validate_agent_id(agent_id: str) -> None:
        if not agent_id or not isinstance(agent_id, str):
            raise ValueError(f"agent_id must be a non-empty string, got {type(agent_id).__name__}")
        if os.sep in agent_id or (os.altsep and os.altsep in agent_id):
            raise ValueError(f"agent_id contains path separator: '{agent_id}'")
        if ".." in agent_id:
            raise ValueError(f"agent_id contains parent directory reference: '{agent_id}'")
        if not re.match(r'^[a-zA-Z0-9_.-]+$', agent_id):
            raise ValueError(
                f"agent_id contains unsafe characters: '{agent_id}'"
            )
