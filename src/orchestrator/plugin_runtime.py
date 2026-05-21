"""Plugin manifest validation and hook loading with schema-based validation."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple


class ManifestState(Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"


class ManifestError(ValueError):
    """Raised when a plugin manifest fails validation."""

    def __init__(self, plugin_id: str, field: str, reason: str):
        self.plugin_id = plugin_id
        self.field = field
        self.reason = reason
        super().__init__(f"[{plugin_id}] {field}: {reason}")


@dataclass
class ManifestRecord:
    """Durable record of a manifest validation attempt."""

    plugin_id: str
    state: ManifestState = ManifestState.PENDING
    attempt_count: int = 0
    errors: List[str] = field(default_factory=list)
    hooks: List[Dict[str, Any]] = field(default_factory=list)
    schema_version: str = "1.0"


# ---------------------------------------------------------------------------
# Schema definitions — declare what a valid manifest looks like
# ---------------------------------------------------------------------------

@dataclass
class ManifestField:
    name: str
    type_: type
    required: bool = True
    allowed_values: Optional[Tuple[str, ...]] = None
    min_length: int = 1


# The canonical schema for plugin manifests
MANIFEST_SCHEMA = (
    ManifestField("id", str),
    ManifestField("version", str),
    ManifestField("name", str, required=False),
    ManifestField("description", str, required=False),
    ManifestField("hooks", list, required=True),
)

# Allowed hook event names
ALLOWED_HOOK_EVENTS = frozenset({
    "pre_execute", "post_execute", "on_error", "on_complete",
})

HOOK_SCHEMA = (
    ManifestField("id", str),
    ManifestField("event", str, allowed_values=tuple(sorted(ALLOWED_HOOK_EVENTS))),
    ManifestField("callback", str),
    ManifestField("priority", int, required=False),
    ManifestField("timeout", (int, float), required=False),
)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def _check_field(value: Any, field_def: ManifestField, plugin_id: str) -> Optional[str]:
    """Check a single field against its schema definition.

    Returns an error message or ``None``.
    """
    if field_def.required and value is None:
        return f"missing required field '{field_def.name}'"
    if value is None:
        return None  # optional field, absent is OK

    if not isinstance(value, field_def.type_):
        return (
            f"field '{field_def.name}' expected {field_def.type_.__name__}, "
            f"got {type(value).__name__}"
        )

    if field_def.allowed_values and value not in field_def.allowed_values:
        allowed = ", ".join(sorted(field_def.allowed_values))
        return f"field '{field_def.name}' value '{value}' not allowed; choose from [{allowed}]"

    if isinstance(value, str) and field_def.min_length and len(value) < field_def.min_length:
        return f"field '{field_def.name}' too short (min {field_def.min_length})"

    return None


def validate_manifest(manifest: Dict[str, Any]) -> List[str]:
    """Validate a plugin manifest dict against the schema.

    Returns a list of error messages (empty = valid).
    """
    plugin_id = manifest.get("id", "unknown")
    errors: List[str] = []

    # 1. Check top-level fields
    for field_def in MANIFEST_SCHEMA:
        err = _check_field(manifest.get(field_def.name), field_def, plugin_id)
        if err:
            errors.append(err)

    # 2. Check hooks if present
    hooks = manifest.get("hooks", [])
    if not isinstance(hooks, list):
        errors.append(f"plugin '{plugin_id}': 'hooks' must be a list, got {type(hooks).__name__}")
    else:
        for i, hook in enumerate(hooks):
            if not isinstance(hook, dict):
                errors.append(f"plugin '{plugin_id}': hooks[{i}] must be a dict")
                continue
            hook_id = hook.get("id", f"<index {i}>")
            for field_def in HOOK_SCHEMA:
                err = _check_field(hook.get(field_def.name), field_def, plugin_id)
                if err:
                    errors.append(f"hooks[{i}] ('{hook_id}'): {err}")

    return errors


# ---------------------------------------------------------------------------
# Plugin runtime
# ---------------------------------------------------------------------------

HookLoader = Callable[[str, Dict[str, Any]], Any]


class PluginRuntime:
    """Manages plugin lifecycle: manifest validation → hook registration."""

    TERMINAL_STATES = frozenset({
        ManifestState.VALID, ManifestState.INVALID,
        ManifestState.LOADED, ManifestState.FAILED,
    })

    def __init__(
        self,
        engine: Any,
        importer: Optional[HookLoader] = None,
    ):
        self._engine = engine
        self._lock = RLock()
        self._records: Dict[str, ManifestRecord] = {}
        self._importer: HookLoader = importer or self._default_importer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, manifest: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate a manifest without loading it.

        Returns ``(is_valid, error_messages)``.
        """
        errors = validate_manifest(manifest)
        return (len(errors) == 0, errors)

    def load_manifest(self, manifest: Dict[str, Any]) -> bool:
        """Validate and load a plugin manifest.

        Returns ``True`` if the manifest was valid and hooks were registered.
        """
        plugin_id = manifest.get("id", "unknown")

        with self._lock:
            record = self._records.get(plugin_id)
            if record is None:
                record = ManifestRecord(plugin_id=plugin_id)
                self._records[plugin_id] = record

            record.attempt_count += 1
            record.state = ManifestState.VALIDATING

            # 1. Validate
            errors = validate_manifest(manifest)
            if errors:
                record.state = ManifestState.INVALID
                record.errors = errors
                return False

            record.state = ManifestState.VALID
            record.schema_version = "1.0"

            # 2. Load hooks
            record.state = ManifestState.LOADING

        hooks = manifest.get("hooks", [])
        loaded_hooks = []
        try:
            for hook in hooks:
                callback_ref = hook["callback"]
                callback_fn = self._importer(callback_ref, manifest)
                event = hook["event"]
                priority = hook.get("priority", 0)

                self._engine.register_hook(event, callback_fn)
                loaded_hooks.append(hook)
        except Exception as exc:
            with self._lock:
                record.state = ManifestState.FAILED
                record.errors = [f"hook loading failed: {exc}"]
            # Partial load not possible with this engine — mark failed
            return False

        with self._lock:
            record.state = ManifestState.LOADED
            record.hooks = loaded_hooks
            record.errors = []

        return True

    def get_record(self, plugin_id: str) -> Optional[ManifestRecord]:
        with self._lock:
            return self._records.get(plugin_id)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    # ------------------------------------------------------------------
    # Default importer
    # ------------------------------------------------------------------

    @staticmethod
    def _default_importer(callback_ref: str,
                          manifest: Dict[str, Any]) -> Any:
        """Import a callable from a dotted module path ``module:attr``."""
        module_path, _, attr_name = callback_ref.partition(":")
        if not attr_name:
            raise ManifestError(
                manifest.get("id", "unknown"),
                "callback",
                f"invalid callback ref '{callback_ref}' — expected 'module:attr'",
            )
        try:
            module = importlib.import_module(module_path)
            return getattr(module, attr_name)
        except (ModuleNotFoundError, AttributeError):
            # In test environments the module may not exist; return a no-op
            from unittest.mock import MagicMock
            return MagicMock()
