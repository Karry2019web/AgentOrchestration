"""Exception context sanitizer for safe error tracking."""

import traceback
from typing import Any, Dict, Optional

_SAFE_FIELDS = {
    "task_id", "execution_id", "agent_id", "error", "error_type",
    "reason", "message", "status_code", "duration", "timeout",
    "retry_after", "resource", "id", "name", "type", "status",
    "host", "port", "version", "count", "total", "timestamp",
    "started_at", "completed_at", "attempt", "max_attempts",
}

_UNSAFE_PATTERNS = [
    "payload", "body", "data", "params", "input", "request",
    "response", "raw", "content", "args", "kwargs", "local",
    "variable", "secret", "token", "password", "key", "auth",
]


def _is_safe_field(name: str) -> bool:
    """Check if a field name is safe to include in exception context."""
    lower = name.lower().strip()
    if lower in _SAFE_FIELDS:
        return True
    for pattern in _UNSAFE_PATTERNS:
        if pattern in lower:
            return False
    return True


def _sanitize_value(value: Any, depth: int = 0, max_depth: int = 3) -> Any:
    """Recursively sanitize a value, stripping unsafe fields."""
    if depth >= max_depth:
        return _summarize(value)
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if _is_safe_field(k):
                result[k] = _sanitize_value(v, depth + 1, max_depth)
            else:
                result[k] = _summarize(v)
        return result
    elif isinstance(value, (list, tuple)):
        if len(value) > 5:
            return [f"<{len(value)} items>"]
        return [_sanitize_value(v, depth + 1, max_depth) for v in value]
    elif isinstance(value, (int, float, bool)):
        return value
    elif value is None:
        return None
    else:
        s = str(value)
        return s[:200] + "..." if len(s) > 200 else s


def _summarize(value: Any) -> str:
    """Create a safe summary string for an unsafe value."""
    if value is None:
        return "<null>"
    t = type(value).__name__
    s = str(value)
    if not s:
        return f"<empty {t}>"
    return f"<{t}: {s[:50]}...>" if len(s) > 50 else f"<{t}: {s}>"


def sanitize_exception_context(
    context: Optional[Dict] = None,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict:
    """Build a sanitized context dict with only approved identifiers."""
    result: Dict = {}
    if task_id:
        result["task_id"] = task_id
    if execution_id:
        result["execution_id"] = execution_id
    if agent_id:
        result["agent_id"] = agent_id
    if context:
        safe_ctx = {}
        for k, v in context.items():
            if _is_safe_field(k):
                safe_ctx[k] = _sanitize_value(v)
            else:
                safe_ctx[k] = _summarize(v)
        result["context"] = safe_ctx
    return result


def format_exception_event(
    exc: BaseException,
    context: Optional[Dict] = None,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict:
    """Build a safe exception event dict with sanitized context."""
    event: Dict = {
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
    }
    safe_ctx = sanitize_exception_context(context, task_id, execution_id, agent_id)
    if safe_ctx:
        event["context"] = safe_ctx
    return event
