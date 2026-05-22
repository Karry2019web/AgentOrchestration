"""Task Monitor — Long-polling worker with live API key revalidation.

The core fix for bounty #2227: when a task monitor polls for new work,
it revalidates its API key on every cycle instead of trusting stale
credentials. This ensures that revoked, expired, disabled-user, or
insufficiently-scoped keys are rejected immediately, even during
long-running polling connections.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from src.common.auth import APIKeyScope, key_manager
from src.common.errors import AuthenticationError

logger = logging.getLogger(__name__)


class TaskMonitor:
    """Long-polling worker that revalidates auth on every cycle.

    The monitor connects to the orchestrator engine and pulls pending
    tasks. Before processing each task it revalidates the API key so
    that a revocation taking effect mid-session is respected immediately.
    """

    def __init__(
        self,
        engine,
        token: str = "",
        poll_interval: float = 1.0,
        max_batch: int = 10,
    ):
        self.engine = engine
        self._token = token
        self._poll_interval = poll_interval
        self._max_batch = max_batch
        self._running = False
        self._active_sessions: Dict[str, str] = {}  # session_id -> key_id

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        self._token = value

    async def start(self) -> None:
        """Start the long-polling monitor loop."""
        self._running = True
        logger.info("Task monitor started")

        while self._running:
            try:
                await self._poll_cycle()
            except AuthenticationError as e:
                logger.error(f"Authentication rejected during polling: {e}")
                # Stop polling — key is no longer valid
                self._running = False
                raise
            except Exception as e:
                logger.warning(f"Poll cycle error: {e}")
                # Non-auth errors are transient; retry after interval
                await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False
        logger.info("Task monitor stopped")

    async def _poll_cycle(self) -> None:
        """One polling cycle: revalidate key, then pull and dispatch tasks."""

        # --- LIVE REVALIDATION (the core fix) ---
        # On every poll cycle, check that the API key is still valid.
        # This catches mid-session revocations, expirations, and
        # user disablements that happen between polls.
        validation = key_manager.validate(self._token, APIKeyScope.READ)
        if not validation:
            raise AuthenticationError(
                f"Task monitor key rejected during poll: {validation.reason}"
            )

        key_id = validation.key.key_id if validation.key else "unknown"
        tasks_processed = 0

        while tasks_processed < self._max_batch:
            task = await self.engine.scheduler.dequeue()
            if task is None:
                break

            # Revalidate WRITE scope before executing each task
            write_validation = key_manager.validate(self._token, APIKeyScope.WRITE)
            if not write_validation:
                logger.warning(
                    f"Task {task.get('id')} skipped: "
                    f"key lacks WRITE scope or was revoked: {write_validation.reason}"
                )
                self.engine.scheduler.fail(task.get("id", "unknown"))
                continue

            self._active_sessions[task["id"]] = key_id
            asyncio.create_task(self._process_task(task, key_id))
            tasks_processed += 1

        await asyncio.sleep(self._poll_interval)

    async def _process_task(self, task: Dict, key_id: str) -> None:
        """Process a single task with scope-appropriate auth."""
        try:
            result = await self.engine._execute_task(task)
            self.engine.scheduler.complete(task["id"])
            logger.info(f"Task {task['id']} completed by key {key_id}")
        except Exception as e:
            logger.error(f"Task {task['id']} failed: {e}")
            self.engine.scheduler.fail(task["id"])
        finally:
            self._active_sessions.pop(task["id"], None)

    def get_active_sessions(self) -> Dict[str, str]:
        return dict(self._active_sessions)
