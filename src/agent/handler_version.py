"""
Handler version compatibility — Semver-aware version checks and cache invalidation
for agent handler registrations and resolutions.

Provides:
- Semver parsing and comparison
- Version compatibility matrix (which versions of a handler are compatible)
- Cached handler resolution with automatic invalidation on version change
- Plugin upgrade path validation with safe-defer semantics
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class VersionComparison(Enum):
    MAJOR = "major"      # Breaking change — incompatible
    MINOR = "minor"      # Backward-compatible addition
    PATCH = "patch"      # Bugfix — always compatible
    EXACT = "exact"      # Identical versions
    NONE = "none"        # No version available


@dataclass
class SemVer:
    """Semantic version 2.0.0 parser and comparator."""
    major: int = 0
    minor: int = 0
    patch: int = 0
    pre_release: str = ""
    build: str = ""

    @classmethod
    def parse(cls, version_str: str) -> "SemVer":
        """Parse a semver string. Falls back to 0.0.0 on failure."""
        if not version_str:
            return cls()
        try:
            core = version_str.split("+")[0]  # strip build metadata
            parts = core.split("-")           # pre-release
            ver_parts = parts[0].split(".")
            major = int(ver_parts[0]) if len(ver_parts) > 0 else 0
            minor = int(ver_parts[1]) if len(ver_parts) > 1 else 0
            patch = int(ver_parts[2]) if len(ver_parts) > 2 else 0
            pre_release = parts[1] if len(parts) > 1 else ""
            build = version_str.split("+")[1] if "+" in version_str else ""
            return cls(major=major, minor=minor, patch=patch,
                       pre_release=pre_release, build=build)
        except (ValueError, IndexError):
            logger.warning(f"Failed to parse version: {version_str}, falling back to 0.0.0")
            return cls()

    def is_compatible_with(self, other: "SemVer", allow_minor: bool = True) -> Tuple[bool, VersionComparison]:
        """Check compatibility with another version.
        
        Args:
            other: The target version to compare against.
            allow_minor: If True, minor version bumps are considered compatible.
                         If False, only exact patch versions are compatible.
        
        Returns:
            Tuple of (is_compatible, comparison_type).
        """
        if self.major != other.major:
            return False, VersionComparison.MAJOR
        if not allow_minor and self.minor != other.minor:
            return False, VersionComparison.MINOR
        if self.minor != other.minor:
            return True, VersionComparison.MINOR
        if self.patch != other.patch:
            return True, VersionComparison.PATCH
        return True, VersionComparison.EXACT

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre_release:
            base += f"-{self.pre_release}"
        if self.build:
            base += f"+{self.build}"
        return base

    def __eq__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.pre_release) ==                (other.major, other.minor, other.patch, other.pre_release)


class HandlerVersionError(ValueError):
    """Raised when a handler version is incompatible."""
    pass


@dataclass
class HandlerRegistration:
    """A registered handler with version metadata."""
    handler_id: str
    name: str
    version: SemVer
    handler_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    compatible_versions: Set[str] = field(default_factory=set)

    def is_compatible(self, other_version: SemVer, allow_minor: bool = True) -> Tuple[bool, VersionComparison]:
        """Check if this handler is compatible with a given version.
        
        First checks the explicit compatibility set, then falls back
        to semver comparison.
        """
        str_other = str(other_version)
        if self.compatible_versions and str_other in self.compatible_versions:
            return True, VersionComparison.EXACT
        return self.version.is_compatible_with(other_version, allow_minor=allow_minor)


class HandlerVersionRegistry:
    """Tracks handler registrations and their version compatibility.
    
    Maintains a version-indexed registry that allows:
    - Registration of handlers with version metadata
    - Lookup by name and optional version constraint
    - Cache invalidation when a handler's version changes
    - Detection of incompatible upgrades during plugin transitions
    """
    
    def __init__(self):
        self._handlers_by_name: Dict[str, List[HandlerRegistration]] = {}
        self._handlers_by_id: Dict[str, HandlerRegistration] = {}
        self._resolution_cache: Dict[str, str] = {}  # cache_key -> handler_id
        self._cache_version_stamps: Dict[str, str] = {}  # handler_name -> version_stamp
    
    def register(self, name: str, version_str: str, handler_type: str,
                 metadata: Optional[Dict] = None,
                 compatible_versions: Optional[List[str]] = None) -> str:
        """Register a handler with version.
        
        Returns the handler ID.
        Raises HandlerVersionError if the version string is invalid.
        """
        version = SemVer.parse(version_str)
        if version.major == 0 and version.minor == 0 and version.patch == 0:
            raise HandlerVersionError(
                f"Invalid version '{version_str}' for handler '{name}': "
                "could not be parsed"
            )
        
        handler_id = f"{name}@{version_str}"
        registration = HandlerRegistration(
            handler_id=handler_id,
            name=name,
            version=version,
            handler_type=handler_type,
            metadata=metadata or {},
            compatible_versions=set(compatible_versions or []),
        )
        
        if name not in self._handlers_by_name:
            self._handlers_by_name[name] = []
        self._handlers_by_name[name].append(registration)
        self._handlers_by_id[handler_id] = registration
        
        # Invalidate caches for this handler name
        self._invalidate_cache_for(name)
        
        logger.info(f"Registered handler '{name}' version {version_str} (id: {handler_id})")
        return handler_id
    
    def get_handler(self, name: str, version_constraint: Optional[str] = None,
                    allow_minor: bool = True) -> Optional[HandlerRegistration]:
        """Resolve a handler by name with optional version constraint.
        
        Uses a cache keyed on (name, version_constraint) and invalidates
        when registrations change.
        """
        cache_key = f"{name}:{version_constraint or 'latest'}"
        
        # Check resolution cache
        if cache_key in self._resolution_cache:
            cached_id = self._resolution_cache[cache_key]
            cached = self._handlers_by_id.get(cached_id)
            if cached:
                return cached
        
        # Resolve
        registrations = self._handlers_by_name.get(name, [])
        if not registrations:
            return None
        
        if version_constraint:
            constraint_ver = SemVer.parse(version_constraint)
            # Find the best matching registration
            best = None
            for reg in registrations:
                compatible, _ = reg.is_compatible(constraint_ver, allow_minor)
                if compatible:
                    if best is None:
                        best = reg
                    # Prefer exact match over minor over patch
                    elif reg.version == constraint_ver:
                        best = reg
            if best:
                self._resolution_cache[cache_key] = best.handler_id
            return best
        else:
            # Return the latest version
            latest = max(registrations, key=lambda r: (r.version.major, r.version.minor, r.version.patch))
            self._resolution_cache[cache_key] = latest.handler_id
            return latest
    
    def validate_upgrade(self, name: str, current_version: str, new_version: str) -> Tuple[bool, str]:
        """Validate that upgrading a handler from current_version to new_version is safe.
        
        Returns (is_safe, reason).
        """
        current = SemVer.parse(current_version)
        new = SemVer.parse(new_version)
        
        compatible, comparison = current.is_compatible_with(new, allow_minor=True)
        
        if comparison == VersionComparison.MAJOR:
            # Check if the new major version is explicitly listed as compatible
            registrations = self._handlers_by_name.get(name, [])
            for reg in registrations:
                if reg.version == new and str(current) in reg.compatible_versions:
                    return True, f"Major upgrade explicitly allowed via compatibility declaration"
            
            return False, (
                f"Major version upgrade {current_version} -> {new_version} for "
                f"handler '{name}' is incompatible. Breaking changes detected."
            )
        
        return True, f"Safe upgrade: {comparison.value} change ({current_version} -> {new_version})"
    
    def invalidate_handler(self, name: str) -> None:
        """Invalidate all cached resolutions for a handler name.
        Called when a handler's registration changes (upgrade, downgrade, removal).
        """
        self._invalidate_cache_for(name)
        logger.info(f"Invalidated resolution caches for handler '{name}'")
    
    def _invalidate_cache_for(self, name: str) -> None:
        """Remove all cache entries that reference the given handler name."""
        keys_to_remove = [k for k in self._resolution_cache if k.startswith(f"{name}:")]
        for k in keys_to_remove:
            del self._resolution_cache[k]
    
    def list_handlers(self, name: Optional[str] = None) -> List[HandlerRegistration]:
        """List registered handlers, optionally filtered by name."""
        if name:
            return list(self._handlers_by_name.get(name, []))
        result = []
        for registrations in self._handlers_by_name.values():
            result.extend(registrations)
        return result
    
    def get_versions(self, name: str) -> List[str]:
        """Return all registered version strings for a handler name."""
        return [str(r.version) for r in self._handlers_by_name.get(name, [])]
    
    def remove_handler(self, handler_id: str) -> bool:
        """Remove a handler registration and invalidate caches."""
        reg = self._handlers_by_id.pop(handler_id, None)
        if reg is None:
            return False
        name = reg.name
        registrations = self._handlers_by_name.get(name, [])
        self._handlers_by_name[name] = [r for r in registrations if r.handler_id != handler_id]
        self._invalidate_cache_for(name)
        logger.info(f"Removed handler '{handler_id}'")
        return True
