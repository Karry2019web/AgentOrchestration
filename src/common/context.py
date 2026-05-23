"""Execution context management — isolates and restores contextvars across nested agent calls."""

import contextvars
from typing import Any, Dict, Optional


# Well-known context variables used through the orchestration lifecycle.
request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)
auth_token: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "auth_token", default=None
)
source_agent: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "source_agent", default=None
)
execution_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "execution_id", default=None
)
correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)


# Registry of all context variables managed by this module.
_ALL_VARS = [request_id, auth_token, source_agent, execution_id, correlation_id]


def snapshot() -> Dict[str, Any]:
    """Capture the current value of every managed context variable."""
    return {var.name: var.get() for var in _ALL_VARS}


def restore(state: Dict[str, Any]) -> None:
    """Restore every managed context variable from a previously captured snapshot."""
    for var in _ALL_VARS:
        val = state.get(var.name)
        if val is not None:
            var.set(val)


class ContextScope:
    """Context manager that snapshots the current context on enter and restores it on exit.

    Usage:
        with ContextScope():
            # context is isolated here
            await nested_call()
        # context is restored to pre-enter values
    """

    def __init__(self):
        self._saved: Dict[str, Any] = {}

    def __enter__(self):
        self._saved = snapshot()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        restore(self._saved)
        return False


async def run_with_isolated_context(coro):
    """Run an awaitable inside a fresh isolated context scope.

    When the coroutine completes the calling context is restored exactly
    as it was before the call — even if the coroutine mutated contextvars.
    """
    saved = snapshot()
    try:
        return await coro
    finally:
        restore(saved)

# 2026-05-23T07:00:00 update

