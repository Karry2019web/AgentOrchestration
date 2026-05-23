"""Configuration management module."""

import os
import json
from typing import Any, Dict, Optional


def _coerce_value(value: str) -> Any:
    """Coerce environment variable strings to appropriate Python types.

    Tries int, then float, then leaves as string.
    """
    # Strip whitespace
    stripped = value.strip()
    # Try integer
    try:
        return int(stripped)
    except ValueError:
        pass
    # Try float
    try:
        return float(stripped)
    except ValueError:
        pass
    # Leave as string
    return value


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
                self._set_nested(config_key, _coerce_value(value))

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
