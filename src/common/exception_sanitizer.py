"""Exception context sanitizer — strips raw payloads from error tracking.

Prevents raw task payloads, unfiltered local variables, and structured context
from leaking into exception events sent to third-party or shared error tooling.
"""

from typing import Any, Dict, Optional, Set


# Fields that are always safe to keep in exception context.
_SAFE_FIELDS: Set[str] = {
    "task_id",
    "execution_id",
    "agent_id",
    "error",
    "error_type",
    "reason",
    "message",
    "status_code",
    "duration",
    "timeout",
    "retry_after",
    "resource",
}

# Field name substrings that indicate raw / sensitive payload data.
_UNSAFE_PATTERNS: Set[str] = {
    "payload",
    "body",
    "data",
    "params",
    "input",
    "request",
    "response",
    "raw",
    "content",
    "args",
    "kwargs",
    "local",
    "variable",
    "context",
    "config",
    "settings",
    "env",
    "secret",
    "token",
    "password",
    "key",
    "auth",
}


def _is_safe_field(name: str) -> bool:
    """Check whether a context field is safe for exception reporting."""
    name_lower = name.lower()
    if name_lower in _SAFE_FIELDS:
        return True
    for pattern in _UNSAFE_PATTERNS:
        if pattern in name_lower:
            return False
    return True


def _sanitize_value(value: Any, depth: int = 0, max_depth: int = 3) -> Any:
    """Recursively sanitize a value, replacing unsafe structures."""
    if depth > max_depth:
        return _summarize(value)
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and not _is_safe_field(k):
                sanitized[k] = _summarize(v)
            else:
                sanitized[k] = _sanitize_value(v, depth + 1, max_depth)
        return sanitized
    if isinstance(value, (list, tuple)):
        if len(value) > 5:
            return [f"<{len(value)} items>"]
        return [_sanitize_value(v, depth + 1, max_depth) for v in value]
    if isinstance(value, (int, float, bool, type(None))):
        return value
    if isinstance(value, str) and len(value) > 500:
        return value[:200] + "..."
    return value


def _summarize(value: Any) -> str:
    """Return a type-aware summary of a value for safe logging."""
    if isinstance(value, dict):
        return f"<dict({len(value)} keys)>"
    if isinstance(value, (list, tuple)):
        return f"<{type(value).__name__}({len(value)})>"
    if isinstance(value, str):
        return f"<string({len(value)} chars)>"
    if isinstance(value, bytes):
        return f"<bytes({len(value)})>"
    return f"<{type(value).__name__}>"


def sanitize_exception_context(
    context: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Sanitize exception context, keeping only safe fields.

    Args:
        context: Original exception context dict (may contain raw payloads).
        task_id: Stable task identifier to include in the sanitized output.
        execution_id: Stable execution identifier (optional).
        agent_id: Stable agent identifier (optional).

    Returns:
        Sanitized context dict with only approved fields.
    """
    safe: Dict[str, Any] = {}
    if task_id:
        safe["task_id"] = task_id
    if execution_id:
        safe["execution_id"] = execution_id
    if agent_id:
        safe["agent_id"] = agent_id
    if context:
        safe["context"] = _sanitize_value(context)
    return safe


def format_exception_event(
    exc: BaseException,
    context: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a sanitized exception event dict for error tracking.

    The returned dict contains only safe identifiers and error class
    information — no raw payloads, local variables, or task content.
    """
    event: Dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    safe_ctx = sanitize_exception_context(context, task_id, execution_id, agent_id)
    if safe_ctx:
        event["context"] = safe_ctx
    return event
