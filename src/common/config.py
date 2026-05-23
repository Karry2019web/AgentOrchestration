"""Configuration management module."""

import os
import json
from typing import Any, Dict, Optional


class Config:
    def __init__(self, config_path: Optional[str] = None):
        self._data: Dict[str, Any] = {}
        if config_path:
            self.load(config_path)
        self._load_env_overrides()

    def load(self, path: str) -> None:
        with open(path) as f:
            self._data = json.load(f)

    def _load_env_overrides(self) -> None:
        prefix = "AO_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower().replace("_", ".")
                self._set_nested(config_key, value)

    def _set_nested(self, key: str, value: Any) -> None:
        parts = key.split(".")
        current = self._data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def get(self, key: str, default: Any = None) -> Any:
        parts = key.split(".")
        current = self._data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return default
            else:
                return default
        return current

    def set(self, key: str, value: Any) -> None:
        self._set_nested(key, value)

    def to_dict(self) -> Dict:
        return self._data

    @staticmethod
    def validate_resource_limits(cpu_time: int, memory_mb: int, disk_mb: int) -> None:
        """Validate sandbox resource limit configuration.

        Args:
            cpu_time: CPU time limit in seconds.
            memory_mb: Memory limit in megabytes.
            disk_mb: Disk space limit in megabytes.

        Raises:
            ValueError: If any resource limit is negative or zero.
        """
        if not isinstance(cpu_time, int) or cpu_time <= 0:
            raise ValueError(f"cpu_time must be a positive integer, got {cpu_time!r}")
        if not isinstance(memory_mb, int) or memory_mb <= 0:
            raise ValueError(f"memory_mb must be a positive integer, got {memory_mb!r}")
        if not isinstance(disk_mb, int) or disk_mb <= 0:
            raise ValueError(f"disk_mb must be a positive integer, got {disk_mb!r}")
