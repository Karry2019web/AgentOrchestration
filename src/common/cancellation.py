"""Request cancellation context — structured cancellation propagation for downstream agent calls."""

import asyncio
import logging
from contextvars import ContextVar
from typing import Any, Awaitable, List, Optional, Set, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


_current_scope: ContextVar[Optional["CancellationScope"]] = ContextVar(
    "_current_scope", default=None
)


class CancellationScope:
    """A structured cancellation scope that coordinates task lifecycle.

    All tasks registered in this scope are cancelled when the scope itself
    is cancelled. Nested scopes inherit cancellation from their parent.

    Usage::

        async with CancellationScope() as scope:
            task = scope.create_task(some_coro())
            result = await task
    """

    def __init__(self, timeout: Optional[float] = None):
        self._tasks: Set[asyncio.Task] = set()
        self._cancelled = False
        self._timeout = timeout
        self._parent: Optional[CancellationScope] = None

    async def __aenter__(self) -> "CancellationScope":
        self._parent = _current_scope.get()
        _current_scope.set(self)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        _current_scope.set(self._parent)
        if self._cancelled:
            await self._cancel_all_tasks(wait=True)
        if self._parent and self._parent._cancelled:
            self._cancelled = True
            await self._cancel_all_tasks(wait=True)

    def create_task(self, coro: Awaitable[T], name: Optional[str] = None) -> asyncio.Task[T]:
        task = asyncio.create_task(self._wrap(coro), name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _wrap(self, coro: Awaitable[T]) -> T:
        if self._cancelled:
            raise asyncio.CancelledError("Scope was cancelled before task started")
        if self._parent and self._parent._cancelled:
            self.cancel()
            raise asyncio.CancelledError("Parent scope cancelled")
        try:
            return await coro
        except asyncio.CancelledError:
            self.cancel()
            raise

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        for task in list(self._tasks):
            if not task.done():
                task.cancel()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    async def _cancel_all_tasks(self, wait: bool = False) -> None:
        if not self._tasks:
            return
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        if wait:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()


def current_scope() -> Optional[CancellationScope]:
    return _current_scope.get()


async def run_with_cancellation(coro: Awaitable[T], timeout: Optional[float] = None) -> T:
    async with CancellationScope(timeout=timeout) as scope:
        if timeout is not None:
            task = asyncio.create_task(coro)
            done, _ = await asyncio.wait(
                [task], timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                scope.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise asyncio.TimeoutError()
            return task.result()
        return await coro


class RequestCancellationContext:
    """Request-level cancellation context attached to request.state.

    Provides a simpler API than CancellationScope for route handlers
    that need to register tasks for cancellation on client disconnect.
    """

    def __init__(self):
        self._scope = CancellationScope()

    def register_task(self, coro: Awaitable[T], name: Optional[str] = None) -> asyncio.Task[T]:
        return self._scope.create_task(coro, name=name)

    def cancel(self) -> None:
        self._scope.cancel()

    @property
    def cancelled(self) -> bool:
        return self._scope.cancelled

    @property
    def active_task_count(self) -> int:
        return self._scope.task_count

# 2026-05-23T06:35:00 update
