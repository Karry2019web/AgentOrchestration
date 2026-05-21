"""Authorization-scoped report result cache with TTL and revalidation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple


def _stable_key(value: Any) -> Any:
    """Recursively normalize a value into a stable hashable form."""
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (str(k), _stable_key(v))
                for k, v in value.items()
            )
        )
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_stable_key(item) for item in value), key=repr))
    if isinstance(value, (list, tuple)):
        return tuple(_stable_key(item) for item in value)
    return value


@dataclass(frozen=True)
class AuthContext:
    """Authorization context for a report request."""

    user_id: str
    workspace_id: str
    roles: Tuple[str, ...] = field(default_factory=tuple)
    permissions: Tuple[str, ...] = field(default_factory=tuple)
    auth_token_hash: str = ""

    def __init__(
        self,
        user_id: str,
        workspace_id: str,
        roles: Iterable[str] = (),
        permissions: Iterable[str] = (),
        auth_token_hash: str = "",
    ):
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "workspace_id", workspace_id)
        object.__setattr__(self, "roles", tuple(sorted(set(roles))))
        object.__setattr__(self, "permissions", tuple(sorted(set(permissions))))
        object.__setattr__(self, "auth_token_hash", auth_token_hash)

    def scope_key(self) -> Tuple[Any, ...]:
        return (self.user_id, self.workspace_id, self.roles,
                self.permissions, self.auth_token_hash)


AuthorizeFn = Callable[[str, AuthContext], bool]


@dataclass
class _Entry:
    result: Any
    expires_at: float
    workspace_id: str


_DEFAULT_TTL = 300.0  # 5 minutes


class AuthScopeCache:
    """Thread-safe cache that scopes report results by authorization context.

    Each entry carries:
      - A *query-scope* key (report_id + normalized query params).
      - An *auth-scope* key (user + workspace + roles + permissions).
    Both scopes must match for a cache hit.

    Supports optional TTL expiry and revalidation via an ``authorize`` callback
    that is called at get-time.  If the callback returns ``False`` the entry is
    evicted immediately.
    """

    def __init__(self, default_ttl: float = _DEFAULT_TTL):
        self._lock = RLock()
        self._entries: Dict[Tuple[Any, ...], _Entry] = {}
        self._default_ttl = default_ttl

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_key(self, report_id: str, query: Mapping[str, Any],
                  ctx: AuthContext) -> Tuple[Any, ...]:
        return (report_id, _stable_key(query), ctx.scope_key())

    def _is_expired(self, entry: _Entry) -> bool:
        return time.monotonic() > entry.expires_at

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(
        self,
        report_id: str,
        query: Mapping[str, Any],
        ctx: AuthContext,
        result: Any,
        ttl: Optional[float] = None,
    ) -> None:
        """Store a report result under the given query + auth scope."""
        with self._lock:
            key = self._make_key(report_id, query, ctx)
            self._entries[key] = _Entry(
                result=result,
                expires_at=time.monotonic() + (ttl if ttl is not None
                                               else self._default_ttl),
                workspace_id=ctx.workspace_id,
            )

    def get(
        self,
        report_id: str,
        query: Mapping[str, Any],
        ctx: AuthContext,
        authorize: Optional[AuthorizeFn] = None,
    ) -> Optional[Any]:
        """Retrieve a cached result.

        Returns ``None`` when:
          - No entry exists for the combined key.
          - The entry has expired (evicted).
          - The optional ``authorize`` callback returns ``False`` (evicted).
        """
        key = self._make_key(report_id, query, ctx)

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None

            if self._is_expired(entry):
                del self._entries[key]
                return None

            if authorize is not None and not authorize(report_id, ctx):
                del self._entries[key]
                return None

            # Deep-copy so the caller cannot mutate the cached value.
            from copy import deepcopy
            return deepcopy(entry.result)

    def invalidate_workspace(self, workspace_id: str) -> None:
        """Remove all entries belonging to *workspace_id*."""
        with self._lock:
            self._entries = {
                k: v
                for k, v in self._entries.items()
                if v.workspace_id != workspace_id
            }

    def invalidate_user(self, user_id: str) -> None:
        """Remove all entries belonging to *user_id*.

        Useful when a user's roles / permissions change mid-session.
        Note this is a linear scan — only call when necessary.
        """
        with self._lock:
            self._entries = {
                k: v
                for k, v in self._entries.items()
                if not self._key_belongs_to_user(k, user_id)
            }

    @staticmethod
    def _key_belongs_to_user(key: Tuple[Any, ...],
                             user_id: str) -> bool:
        """Check whether the compound cache key belongs to *user_id*.

        Key structure: (report_id, query_hash, (user_id, ws, roles, perms, ath))
        The user_id is at index 2 (the first element of the scope key tuple).
        """
        if len(key) < 3:
            return False
        scope = key[2]
        if isinstance(scope, tuple) and len(scope) >= 1:
            return scope[0] == user_id
        return False

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._entries.clear()

    @property
    def size(self) -> int:
        """Number of cached entries (approximate, not locked)."""
        return len(self._entries)
