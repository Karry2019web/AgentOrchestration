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

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean config value with strict coercion.

        Accepted truthy strings (case-insensitive): "true", "1", "yes", "on"
        Accepted falsy strings (case-insensitive): "false", "0", "no", "off"

        Raises ValueError if the raw value is a string that does not match
        any accepted boolean representation.

        Non-string values are passed through Python's bool().
        """
        raw = self.get(key, default)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            lower = raw.strip().lower()
            if lower in ("true", "1", "yes", "on"):
                return True
            if lower in ("false", "0", "no", "off"):
                return False
            raise ValueError(
                f"Cannot coerce string {raw!r} to bool for key {key!r}. "
                f"Accepted values: true/false, 1/0, yes/no, on/off"
            )
        if isinstance(raw, (int, float)):
            return raw != 0
        if raw is None:
            return default if isinstance(default, bool) else False
        return bool(raw)

    def set(self, key: str, value: Any) -> None:
        self._set_nested(key, value)

    def to_dict(self) -> Dict:
        return self._data
