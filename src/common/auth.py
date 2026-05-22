"""API key management — creation, revocation, revalidation, and scope enforcement.

Addresses the bug: stale, revoked, or insufficiently scoped API keys accepted
during long-polling in the task monitor. Every protected action revalidates the
key against the latest revocation state.
"""

import time
import uuid
import threading
from typing import Dict, List, Optional, Set


class APIKeyScope:
    """Granular permission scopes for API keys."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    MANAGE_WEBHOOKS = "manage_webhooks"
    MANAGE_KEYS = "manage_keys"

    ALL = {READ, WRITE, ADMIN, MANAGE_WEBHOOKS, MANAGE_KEYS}


class APIKey:
    """An API key with metadata, scopes, and revocation tracking."""

    def __init__(
        self,
        key_id: str,
        label: str,
        scopes: List[str],
        created_by: str,
        expires_at: Optional[float] = None,
    ):
        self.key_id = key_id
        self.label = label
        self.scopes = frozenset(scopes)
        self.created_by = created_by
        self.created_at = time.time()
        self.expires_at = expires_at
        self._revoked = False
        self._revoked_at: Optional[float] = None
        self._revoked_by: Optional[str] = None

    @property
    def is_active(self) -> bool:
        if self._revoked:
            return False
        if self.expires_at and time.time() > self.expires_at:
            return False
        return True

    @property
    def is_revoked(self) -> bool:
        return self._revoked

    def revoke(self, by: str) -> None:
        self._revoked = True
        self._revoked_at = time.time()
        self._revoked_by = by

    def has_scope(self, required: str) -> bool:
        return required in self.scopes

    def to_dict(self) -> Dict:
        return {
            "key_id": self.key_id,
            "label": self.label,
            "scopes": list(self.scopes),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_active": self.is_active,
            "is_revoked": self._revoked,
            "revoked_at": self._revoked_at,
            "revoked_by": self._revoked_by,
        }


class APIKeyManager:
    """Central authority for API key lifecycle and revalidation.

    Thread-safe. Used by the AuthMiddleware (synchronous path) and the
    TaskMonitor (long-polling async path) to revalidate keys on every
    protected operation.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # key_id -> APIKey
        self._keys: Dict[str, APIKey] = {}
        # token_hash -> key_id  (for fast lookup by bearer token)
        self._token_index: Dict[int, str] = {}
        # Users who have been disabled globally
        self._disabled_users: Set[str] = set()

    # --- Key Creation ----------------------------------------------------------

    def create_key(
        self,
        label: str,
        scopes: List[str],
        created_by: str,
        expires_at: Optional[float] = None,
    ) -> APIKey:
        """Register a new API key and return it."""
        key_id = str(uuid.uuid4())
        key = APIKey(key_id, label, scopes, created_by, expires_at)
        with self._lock:
            self._keys[key_id] = key
        return key

    def register_key(self, key_id: str, key: APIKey) -> None:
        """Register a pre-built key (used by tests / seeding)."""
        with self._lock:
            self._keys[key_id] = key

    def index_token(self, token: str, key_id: str) -> None:
        """Associate a bearer token hash with a key ID."""
        with self._lock:
            self._token_index[hash(token)] = key_id

    # --- Key Lookup -----------------------------------------------------------

    def get_key(self, key_id: str) -> Optional[APIKey]:
        with self._lock:
            return self._keys.get(key_id)

    def find_by_token(self, token: str) -> Optional[APIKey]:
        with self._lock:
            key_id = self._token_index.get(hash(token))
            if key_id:
                return self._keys.get(key_id)
        return None

    def list_keys(self, include_revoked: bool = False) -> List[APIKey]:
        with self._lock:
            keys = list(self._keys.values())
        if not include_revoked:
            keys = [k for k in keys if k.is_active]
        return keys

    # --- Revocation -----------------------------------------------------------

    def revoke_key(self, key_id: str, by: str) -> bool:
        """Revoke a key. Returns False if key doesn't exist."""
        with self._lock:
            key = self._keys.get(key_id)
            if not key:
                return False
            key.revoke(by)
            return True

    def revoke_keys_for_user(self, user_id: str, by: str) -> int:
        """Revoke all active keys created by a user. Returns count."""
        count = 0
        with self._lock:
            for key in self._keys.values():
                if key.created_by == user_id and key.is_active:
                    key.revoke(by)
                    count += 1
        return count

    # --- User-level Disable ---------------------------------------------------

    def disable_user(self, user_id: str) -> None:
        with self._lock:
            self._disabled_users.add(user_id)

    def enable_user(self, user_id: str) -> None:
        with self._lock:
            self._disabled_users.discard(user_id)

    def is_user_disabled(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._disabled_users

    # --- Revalidation (the core fix) -----------------------------------------

    class ValidationResult:
        """Result of an API key validation check."""

        def __init__(
            self,
            valid: bool,
            reason: str = "",
            key: Optional["APIKey"] = None,
        ):
            self.valid = valid
            self.reason = reason
            self.key = key

        def __bool__(self):
            return self.valid

    def validate(
        self, token: str, required_scope: str = APIKeyScope.READ
    ) -> "ValidationResult":
        """Validate a bearer token for a required scope.

        Checks in order:
        1. Token is present and well-formed
        2. Key exists and is not revoked
        3. Key has not expired
        4. Key has the required scope
        5. Key's owner is not disabled
        """
        if not token or not token.startswith("Bearer "):
            return self.ValidationResult(False, "Missing or malformed Authorization header")

        actual_token = token[len("Bearer "):]
        if not actual_token.strip():
            return self.ValidationResult(False, "Empty token")

        key = self.find_by_token(actual_token)
        if not key:
            return self.ValidationResult(False, "Unknown API key")

        if key.is_revoked:
            return self.ValidationResult(False, "API key has been revoked")

        if not key.is_active:
            if key.expires_at and time.time() > key.expires_at:
                return self.ValidationResult(False, "API key has expired")
            return self.ValidationResult(False, "API key is not active")

        if not key.has_scope(required_scope):
            return self.ValidationResult(
                False,
                f"API key lacks required scope: {required_scope}",
            )

        if self.is_user_disabled(key.created_by):
            return self.ValidationResult(
                False,
                "User account has been disabled",
            )

        return self.ValidationResult(True, "", key)


# Global singleton for the application
key_manager = APIKeyManager()
