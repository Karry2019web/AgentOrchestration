"""SDK decorators for agent definitions."""

import functools
import asyncio
from typing import Any, Callable, Dict, Optional


def task(name: Optional[str] = None, retries: int = 0, timeout: int = 300):
    """Decorator for marking a method as an agent task handler."""
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ValueError("Task retries must be a non-negative integer")

    def decorator(func: Callable) -> Callable:
        func.__task_config__ = {
            "name": name or func.__name__,
            "retries": retries,
            "timeout": timeout,
        }

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout,
                )
                return result
            except asyncio.TimeoutError:
                raise TimeoutError(f"Task {name or func.__name__} timed out after {timeout}s")

        return wrapper
    return decorator


def agent(name: str, version: str = "1.0.0", description: str = ""):
    """Decorator for marking a class as an agent definition."""
    def decorator(cls: type) -> type:
        cls.__agent_config__ = {
            "name": name,
            "version": version,
            "description": description,
        }
        return cls
    return decorator


def on_event(event_type: str):
    """Decorator for marking a method as an event handler."""
    def decorator(func: Callable) -> Callable:
        func.__event_handler__ = event_type

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper
    return decorator
