"""Configuration management module."""

import os
import json
from typing import Any, Dict, Optional

SENSITIVE_KEYS = frozenset({
    "api_key", "apikey",
    "secret", "secret_key", "secretkey",
    "password", "passwd", "pwd",
    "token", "auth_token", "access_token",
    "auth", "authorization",
    "credential", "credentials",
    "private_key", "privatekey",
    "jwt", "jwt_secret",
    "db_password",
})


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

    def to_redacted_dict(self) -> Dict:
        """Return a copy of config with sensitive values masked.

        Recursively walks the config dict and replaces any value whose
        key (or parent key chain) contains a sensitive pattern with
        ``"****"``. Safe for diagnostic / log output.
        """
        def _redact(value: Any, key_path: str = "") -> Any:
            if isinstance(value, dict):
                return {
                    k: _redact(v, f"{key_path}.{k}" if key_path else k)
                    for k, v in value.items()
                }
            if isinstance(value, list):
                return [_redact(item, key_path) for item in value]
            parts = key_path.lower().replace("-", "_").split(".")
            if any(part in SENSITIVE_KEYS for part in parts):
                return "****"
            return value
        return _redact(self._data)

