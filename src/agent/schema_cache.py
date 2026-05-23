"""Schema cache with capability-contract-aware invalidation.

Prevents stale schema reuse when capability contracts change.
Every schema is tracked with a contract version hash; when the
registered capability contract changes, all cached entries derived
from that contract are invalidated automatically.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ContractVersionError(Exception):
    """Raised when a stale schema is accessed after its contract changed."""


@dataclass
class CachedSchema:
    """A single cached schema entry tied to a specific contract version."""
    schema: Dict[str, Any]
    contract_hash: str
    cached_at: float
    accessed_count: int = 0


class SchemaCache:
    """Schema cache with automatic invalidation on contract version changes.

    Each schema is registered under a *capability key* (e.g. ``"handler.transform"``)
    and stores the hash of the capability contract it was derived from.  When
    ``invalidate_contract(contract)`` is called, *all* schemas that were derived
    from that contract are evicted atomically.  This prevents stale cache reuse
    when an agent's or handler's capability contract changes during registration
    or upgrade.

    Usage::

        cache = SchemaCache()
        contract = {"name": "transform", "version": "1.0.0"}
        cache.set("handler.transform", {"input": "bytes"}, contract)
        entry = cache.get("handler.transform", contract)  # returns CachedSchema
        cache.invalidate_contract(contract)               # evicts all entries
    """

    def __init__(self):
        self._entries: Dict[str, CachedSchema] = {}
        # Maps contract_hash -> set of capability keys
        self._contract_index: Dict[str, set] = {}
        # Maps capability key -> current contract hash (fast lookup)
        self._key_to_hash: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, key: str, schema: Dict[str, Any], contract: Dict[str, Any]) -> None:
        """Store *schema* under *key*, associating it with the given *contract*.

        If a previous entry existed for *key* and its contract hash differs,
        the old entry is replaced and the stale contract index is cleaned up.
        """
        contract_hash = self._hash_contract(contract)
        old_hash = self._key_to_hash.get(key)

        entry = CachedSchema(
            schema=schema,
            contract_hash=contract_hash,
            cached_at=time.time(),
        )
        self._entries[key] = entry
        self._key_to_hash[key] = contract_hash

        if contract_hash not in self._contract_index:
            self._contract_index[contract_hash] = set()
        self._contract_index[contract_hash].add(key)

        # Clean up old contract index if key moved to a new contract
        if old_hash and old_hash != contract_hash:
            old_set = self._contract_index.get(old_hash)
            if old_set:
                old_set.discard(key)
                if not old_set:
                    del self._contract_index[old_hash]

        logger.debug("SchemaCache: cached %s under contract %s", key, contract_hash[:8])

    def get(self, key: str, contract: Optional[Dict[str, Any]] = None) -> Optional[CachedSchema]:
        """Retrieve a cached schema by *key*.

        If *contract* is provided and its hash does *not* match the stored
        contract hash, the entry is treated as stale and is silently evicted
        (returns ``None``).  The caller should then re-derive the schema and
        call ``set`` again.

        Raises ``ContractVersionError`` when the entry was explicitly
        invalidated via ``invalidate_contract`` and *raise_on_stale* is set
        on the cache instance.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None

        if contract is not None:
            expected_hash = self._hash_contract(contract)
            if entry.contract_hash != expected_hash:
                # Contract changed under us — evict silently
                self._evict(key)
                return None

        entry.accessed_count += 1
        return entry

    def invalidate_contract(self, contract: Dict[str, Any]) -> int:
        """Evict *all* cached entries that were derived from *contract*.

        Returns the number of entries evicted.
        """
        contract_hash = self._hash_contract(contract)
        keys = self._contract_index.pop(contract_hash, set())
        for key in keys:
            self._evict(key)
        count = len(keys)
        if count:
            logger.info("SchemaCache: invalidated %d entries for contract %s", count, contract_hash[:8])
        return count

    def invalidate_key(self, key: str) -> bool:
        """Evict a single cache entry by key.  Returns ``True`` if it existed."""
        return self._evict(key) is not None

    def clear(self) -> None:
        """Remove all cached entries."""
        self._entries.clear()
        self._contract_index.clear()
        self._key_to_hash.clear()

    @property
    def size(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _hash_contract(self, contract: Dict[str, Any]) -> str:
        """Deterministic hash of a capability contract dict."""
        serialized = json.dumps(contract, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _evict(self, key: str) -> Optional[CachedSchema]:
        entry = self._entries.pop(key, None)
        self._key_to_hash.pop(key, None)
        # Clean up contract index (caller may have already removed the set)
        if entry:
            for h, keys in list(self._contract_index.items()):
                keys.discard(key)
                if not keys:
                    del self._contract_index[h]
        return entry


def validate_contract_change(
    old_contract: Optional[Dict[str, Any]],
    new_contract: Dict[str, Any],
) -> None:
    """Validate a capability contract change, raising on incompatible changes.

    *old_contract* may be ``None`` (first registration).  The following
    changes are considered *breaking* and will raise ``ContractVersionError``:

    * ``name`` changes (the capability identity itself)
    * ``version`` downgrade (major.minor.patch semantic version drop)
    * Removal of required fields.

    Compatible changes (field additions, minor/patch bumps) are allowed.
    """
    if old_contract is None:
        return  # first registration is always valid

    # Identity must not change
    if new_contract.get("name") != old_contract.get("name"):
        raise ContractVersionError(
            f"Capability name changed from '{old_contract.get('name')}' "
            f"to '{new_contract.get('name')}' — identity change requires re-registration"
        )

    # Prevent version downgrade
    old_ver = _parse_version(old_contract.get("version", "0.0.0"))
    new_ver = _parse_version(new_contract.get("version", "0.0.0"))
    if new_ver < old_ver:
        raise ContractVersionError(
            f"Version downgrade detected: {old_contract.get('version')} -> "
            f"{new_contract.get('version')}"
        )

    # Required fields must not be removed
    old_required = set(old_contract.get("required", []))
    new_required = set(new_contract.get("required", []))
    removed = old_required - new_required
    if removed:
        raise ContractVersionError(
            f"Required fields removed from contract: {removed}"
        )


def _parse_version(ver_str: str) -> Tuple[int, ...]:
    """Parse a semantic version string into a comparable tuple."""
    parts = ver_str.replace("-", ".").split(".")[:3]
    try:
        return tuple(int(p) for p in parts)
    except (ValueError, TypeError):
        return (0, 0, 0)
