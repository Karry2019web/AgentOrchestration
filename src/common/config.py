"""Configuration management module."""

import os
import json
from typing import Any, Dict, Optional, Set


class Config:
    # Documented environment override keys — only these AO_ variables
    # are imported from the environment into the config tree.
    _ALLOWED_ENV_OVERRIDES: Set[str] = {
        "AO_LOG_LEVEL",
        "AO_LOG_FORMAT",
        "AO_DB_HOST",
        "AO_DB_PORT",
        "AO_DB_NAME",
        "AO_DB_USER",
        "AO_DB_PASSWORD",
        "AO_REDIS_HOST",
        "AO_REDIS_PORT",
        "AO_REDIS_PASSWORD",
        "AO_API_HOST",
        "AO_API_PORT",
        "AO_API_DEBUG",
        "AO_SECRET_KEY",
        "AO_ENCRYPTION_KEY",
        "AO_AGENT_HEARTBEAT_INTERVAL",
        "AO_AGENT_MAX_RETRIES",
        "AO_QUEUE_MAX_SIZE",
        "AO_QUEUE_VISIBILITY_TIMEOUT",
        "AO_SCHEDULER_INTERVAL",
        "AO_STORAGE_BACKEND",
        "AO_STORAGE_PATH",
        "AO_METRICS_ENABLED",
        "AO_METRICS_PORT",
        "AO_WEBHOOK_RETRY_MAX",
        "AO_WEBHOOK_TIMEOUT",
    }

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
                # Skip if not in the documented allowlist
                if key not in self._ALLOWED_ENV_OVERRIDES:
                    continue
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
