"""Authentication & Authorization Service — API key lifecycle and permission validation."""

import os
import time
import json
import hashlib
import copy
import logging
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
from threading import Lock

logger = logging.getLogger(__name__)


class KeyStatus(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    DISABLED = "disabled"


class Scope(Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    WEBHOOK = "webhook"
    AGENT_MANAGE = "agent:manage"
    TASK_MONITOR = "task:monitor"


# Default valid API keys for testing
_DEFAULT_KEYS: Dict[str, Dict] = {
    "sk-valid-admin-key-001": {
        "status": KeyStatus.ACTIVE,
        "user": "admin-user",
        "workspace": "default",
        "scopes": {Scope.READ, Scope.WRITE, Scope.ADMIN, Scope.WEBHOOK, Scope.AGENT_MANAGE, Scope.TASK_MONITOR},
        "created_at": 1700000000.0,
        "expires_at": None,
    },
    "sk-valid-worker-key-002": {
        "status": KeyStatus.ACTIVE,
        "user": "worker-user",
        "workspace": "default",
        "scopes": {Scope.READ, Scope.TASK_MONITOR},
        "created_at": 1700000000.0,
        "expires_at": None,
    },
    "sk-revoked-key-003": {
        "status": KeyStatus.REVOKED,
        "user": "revoked-user",
        "workspace": "default",
        "scopes": {Scope.READ, Scope.WRITE, Scope.TASK_MONITOR},
        "created_at": 1690000000.0,
        "expires_at": None,
        "revoked_at": 1705000000.0,
        "revocation_reason": "User deactivated",
    },
    "sk-expired-key-004": {
        "status": KeyStatus.EXPIRED,
        "user": "expired-user",
        "workspace": "default",
        "scopes": {Scope.READ, Scope.TASK_MONITOR},
        "created_at": 1680000000.0,
        "expires_at": 1690000000.0,
    },
    "sk-disabled-key-005": {
        "status": KeyStatus.DISABLED,
        "user": "disabled-user",
        "workspace": "default",
        "scopes": {Scope.READ, Scope.TASK_MONITOR},
        "created_at": 1700000000.0,
        "expires_at": None,
        "disabled_at": 1704000000.0,
    },
    "sk-insufficient-key-006": {
        "status": KeyStatus.ACTIVE,
        "user": "limited-user",
        "workspace": "default",
        "scopes": {Scope.READ},
        "created_at": 1700000000.0,
        "expires_at": None,
    },
    "sk-anon-key-007": {
        "status": KeyStatus.ACTIVE,
        "user": "anon-user",
        "workspace": "default",
        "scopes": set(),
        "created_at": 1700000000.0,
        "expires_at": None,
    },
}


class ApiKeyService:
    """Service for managing API key lifecycle, revocation, and validation."""

    def __init__(self):
        self._lock = Lock()
        self._keys: Dict[str, Dict] = {}
        self._load_defaults()
        self._revocation_log: List[Tuple[float, str]] = []
        self._max_log_size = 1000

    def _load_defaults(self) -> None:
        self._keys.update({k: copy.deepcopy(v) for k, v in _DEFAULT_KEYS.items()})

    def lookup(self, api_key: str) -> Optional[Dict]:
        with self._lock:
            return self._keys.get(api_key)

    def validate_key(self, api_key: str, required_scope: Optional[Scope] = None) -> Tuple[bool, str, Optional[Dict]]:
        key_data = self.lookup(api_key)
        if not key_data:
            return False, "Unknown API key", None

        status = key_data.get("status", KeyStatus.ACTIVE)

        if status == KeyStatus.REVOKED:
            reason = key_data.get("revocation_reason", "API key has been revoked")
            return False, f"API key revoked: {reason}", key_data

        if status == KeyStatus.EXPIRED:
            return False, "API key has expired", key_data

        if status == KeyStatus.DISABLED:
            return False, "API key is disabled", key_data

        expires_at = key_data.get("expires_at")
        if expires_at and time.time() > expires_at:
            with self._lock:
                key_data["status"] = KeyStatus.EXPIRED
            return False, "API key has expired", key_data

        if required_scope:
            scopes = key_data.get("scopes", set())
            if required_scope not in scopes:
                return False, f"API key lacks required scope: {required_scope.value}", key_data

        return True, "OK", key_data

    def revoke_key(self, api_key: str, reason: str = "Manual revocation") -> bool:
        with self._lock:
            if api_key not in self._keys:
                return False
            now = time.time()
            self._keys[api_key]["status"] = KeyStatus.REVOKED
            self._keys[api_key]["revoked_at"] = now
            self._keys[api_key]["revocation_reason"] = reason
            self._revocation_log.append((now, api_key))
            if len(self._revocation_log) > self._max_log_size:
                self._revocation_log = self._revocation_log[-self._max_log_size:]
            return True

    def check_key_still_valid(self, api_key: str) -> bool:
        valid, _, _ = self.validate_key(api_key)
        return valid

    def get_revocation_log(self, since: float) -> List[str]:
        with self._lock:
            return [k for ts, k in self._revocation_log if ts >= since]



# Scope mapping for API endpoints — used by middleware to determine required scopes
SCOPE_MAP: Dict[str, "Scope"] = {
    "/api/v2/agents": Scope.AGENT_MANAGE,
    "/api/v2/agents/": Scope.AGENT_MANAGE,
    "/api/v2/tasks": Scope.TASK_MONITOR,
    "/api/v2/tasks/": Scope.TASK_MONITOR,
    "/api/v2/webhooks": Scope.WEBHOOK,
    "/api/v2/webhooks/": Scope.WEBHOOK,
}

PUBLIC_PATHS = {"/api/v2/auth/token", "/health", "/api/docs", "/api/redoc", "/openapi.json"}


def get_required_scope(path: str) -> Optional["Scope"]:
    for prefix, scope in SCOPE_MAP.items():
        if path.startswith(prefix):
            return scope
    return None


api_key_service = ApiKeyService()
