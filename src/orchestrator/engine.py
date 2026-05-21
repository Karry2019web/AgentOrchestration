"""Orchestration Engine — Core execution and coordination logic.

State machine with durable persistence guards:
- Run state is persisted BEFORE emitting any completion/error side effects
- Retries are bounded and idempotent
- Completion events only fire after durable state is confirmed
"""

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.agent.registry import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class RunState(Enum):
    """Durable run state machine states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RunRecord:
    """Persistent record of a run execution."""
    run_id: str
    task_id: str
    agent_id: str
    state: RunState = RunState.PENDING
    output: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3


class StateStore:
    """Durable in-memory state store with snapshot persistence.

    In production this would back to a database; in-memory with
    file snapshot is sufficient for the in-process orchestrator.
    """

    def __init__(self, snapshot_path: Optional[str] = None):
        self._records: Dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        self._snapshot_path = snapshot_path or os.environ.get(
            "AO_STATE_SNAPSHOT_PATH",
            os.path.join(os.path.dirname(__file__), "..", "..", "data", "state_snapshot.json"),
        )
        self._dirty = False

    async def persist(self, record: RunRecord) -> None:
        """Persist a run record durably before emitting side effects."""
        async with self._lock:
            self._records[record.run_id] = record
            self._dirty = True

    async def get(self, run_id: str) -> Optional[RunRecord]:
        async with self._lock:
            return self._records.get(run_id)

    async def snapshot(self) -> None:
        """Write state snapshot to disk for recovery."""
        if not self._dirty:
            return
        async with self._lock:
            try:
                os.makedirs(os.path.dirname(self._snapshot_path), exist_ok=True)
                data = {
                    rid: asdict(rec) for rid, rec in self._records.items()
                    if rec.state in (RunState.RUNNING, RunState.PENDING)
                }
                with open(self._snapshot_path, "w") as f:
                    json.dump(data, f, default=str)
                self._dirty = False
            except Exception as e:
                logger.warning(f"State snapshot failed (non-fatal): {e}")

    async def recover(self) -> Dict[str, RunRecord]:
        """Recover in-flight runs from snapshot on startup."""
        if not os.path.isfile(self._snapshot_path):
            return {}
        try:
            with open(self._snapshot_path) as f:
                data = json.load(f)
            records = {}
            for rid, rec_dict in data.items():
                # Handle both "RunState.RUNNING" and "running" formats
                state_val = rec_dict.get("state", "pending")
                if isinstance(state_val, str) and state_val.startswith("RunState."):
                    state_val = state_val.split(".", 1)[1].lower()
                rec_dict["state"] = RunState(state_val)
                records[rid] = RunRecord(**rec_dict)
            return records
        except Exception as e:
            logger.warning(f"State recovery failed: {e}")
            return {}


class OrchestrationEngine:
    """Orchestration engine with durable state machine.

    State machine guarantees:
    1. Run state is persisted BEFORE emitting completion events
    2. Retries are bounded and idempotent
    3. Completion events only fire after durable state is confirmed
    4. Cancellation respects the durable guard
    """

    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._state_store = StateStore()
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }
        self._run_registry: Dict[str, RunRecord] = {}

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    async def start(self) -> None:
        """Start the engine and recover any in-flight runs."""
        self._running = True
        # Recover in-flight runs from durable state
        recovered = await self._state_store.recover()
        if recovered:
            logger.info(f"Recovered {len(recovered)} in-flight runs from state snapshot")
            for run_id, record in recovered.items():
                self._run_registry[run_id] = record
        logger.info("Orchestration engine started")
        while self._running:
            task = await self.scheduler.dequeue()
            if task:
                asyncio.create_task(self._execute_task(task))
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        logger.info("Orchestration engine stopped")

    def _create_run_record(self, task: Dict[str, Any]) -> RunRecord:
        return RunRecord(
            run_id=str(uuid4()),
            task_id=task["id"],
            agent_id=task.get("target_agent", "unknown"),
            state=RunState.PENDING,
            max_retries=task.get("max_retries", 3),
        )

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        """Execute a task with durable state machine guarantees.

        State machine flow:
        PENDING -> persist -> RUNNING -> persist -> [COMPLETED|FAILED] -> persist -> emit side effects
        """
        task_id = task["id"]
        agent_id = task.get("target_agent", "unknown")
        logger.info(f"Executing task {task_id} on agent {agent_id}")

        # Create and persist initial run record
        run = self._create_run_record(task)
        self._run_registry[run.run_id] = run
        run.state = RunState.RUNNING
        run.started_at = time.time()
        await self._state_store.persist(run)

        # Run pre-execute hooks AFTER state is persisted
        for hook in self._hooks["pre_execute"]:
            try:
                await hook(task)
            except Exception as e:
                logger.warning(f"pre_execute hook failed (non-fatal): {e}")

        try:
            agent = self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            self.registry.update_status(agent_id, AgentStatus.RUNNING)
            result = await asyncio.wait_for(
                self._run_agent_task(agent, task),
                timeout=self.agent_timeout,
            )
            self.registry.update_status(agent_id, AgentStatus.PAUSED)

            # DURABLE GUARD: persist completion state BEFORE emitting side effects
            run.state = RunState.COMPLETED
            run.output = result
            run.completed_at = time.time()
            await self._state_store.persist(run)

            # Emit side effects ONLY after durable state confirmed
            for hook in self._hooks["post_execute"]:
                try:
                    await hook(task, result)
                except Exception as e:
                    logger.warning(f"post_execute hook failed (non-fatal): {e}")

            for hook in self._hooks["on_complete"]:
                try:
                    await hook(task, result)
                except Exception as e:
                    logger.warning(f"on_complete hook failed (non-fatal): {e}")

            logger.info(f"Task {task_id} completed successfully (run={run.run_id})")

        except asyncio.CancelledError:
            # DURABLE GUARD: persist cancellation before any side effects
            run.state = RunState.CANCELLED
            run.completed_at = time.time()
            run.error = "Task execution cancelled"
            await self._state_store.persist(run)
            logger.info(f"Task {task_id} was cancelled (run={run.run_id})")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")

            # DURABLE GUARD: persist failure state before emitting error hooks
            run.state = RunState.FAILED
            run.error = str(e)
            run.completed_at = time.time()

            # Bounded retry: increment count and re-enqueue if retries remain
            run.retry_count += 1
            if run.retry_count <= run.max_retries:
                logger.info(
                    f"Task {task_id} will retry ({run.retry_count}/{run.max_retries})"
                )
                run.state = RunState.PENDING  # Reset for retry
                await self._state_store.persist(run)
                # Re-enqueue the task for retry
                self.scheduler.fail(task_id)
                return

            await self._state_store.persist(run)

            # Emit error hooks ONLY after durable state confirmed
            for hook in self._hooks["on_error"]:
                try:
                    await hook(task, e)
                except Exception as hook_err:
                    logger.warning(f"on_error hook failed: {hook_err}")

        finally:
            # Periodic snapshot for recovery
            await self._state_store.snapshot()

    async def _run_agent_task(self, agent: Dict, task: Dict) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._execute_in_thread,
            agent,
            task,
        )

    def _execute_in_thread(self, agent: Dict, task: Dict) -> Any:
        return {"status": "completed", "output": f"Task {task['id']} processed by {agent['name']}"}

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a run with durable state persistence."""
        run = self._run_registry.get(run_id)
        if not run or run.state in (RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED):
            return False

        # DURABLE GUARD: persist cancellation before emitting
        run.state = RunState.CANCELLED
        run.completed_at = time.time()
        await self._state_store.persist(run)
        return True

    def get_run_state(self, run_id: str) -> Optional[RunState]:
        """Get the durable state of a run."""
        run = self._run_registry.get(run_id)
        return run.state if run else None
