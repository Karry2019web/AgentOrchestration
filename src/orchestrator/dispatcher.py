"""Event Dispatcher — Quarantine unknown event types during rolling version upgrades."""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

class EventKind(Enum):
    TASK_SUBMITTED = "task.submitted"
    TASK_DISPATCHED = "task.dispatched"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_STEP_DONE = "workflow.step_done"
    WORKFLOW_STEP_ERR = "workflow.step_err"
    WORKFLOW_DONE = "workflow.done"
    WORKFLOW_ABORTED = "workflow.aborted"
    AGENT_ONLINE = "agent.online"
    AGENT_OFFLINE = "agent.offline"
    AGENT_HB = "agent.hb"
    AGENT_TIMEOUT = "agent.timeout"
    SCHED_PULSE = "sched.pulse"
    SCHED_DRAIN = "sched.drain"
    @classmethod
    def known(cls):
        return {e.value for e in cls}

class DispatchRevision:
    def __init__(self, attempt=1, revision=1, phase="active", version="1.0.0"):
        self.attempt = attempt; self.revision = revision; self.phase = phase; self.version = version
    def allows(self, target):
        if self.version == target.version: return target.revision > self.revision
        return self.phase == "active" and target.attempt == 1
    def to_dict(self):
        return {"attempt": self.attempt, "revision": self.revision, "phase": self.phase, "version": self.version}
    @classmethod
    def from_dict(cls, data):
        return cls(data.get("attempt", 1), data.get("revision", 1), data.get("phase", "active"), data.get("version", "1.0.0"))
    def __repr__(self):
        return f"DispatchRevision(attempt={self.attempt}, revision={self.revision}, phase={self.phase!r}, version={self.version!r})"

class DispatchQuarantine:
    def __init__(self, known=None):
        self._known = known or EventKind.known(); self._quarantined = []; self._count = 0
    def accept(self, event_type, target, current):
        if event_type not in self._known: return False
        return target.allows(current)
    def quarantine(self, event, reason):
        self._quarantined.append({"event": event, "reason": reason, "timestamp": datetime.now(timezone.utc).isoformat()}); self._count += 1
    @property
    def records(self): return list(self._quarantined)
    @property
    def count(self): return self._count
    def reset(self): self._quarantined.clear(); self._count = 0
    def register(self, event_type): self._known.add(event_type)
    def __repr__(self): return f"DispatchQuarantine(known={len(self._known)}, quarantined={self._count})"

class EventDispatcher:
    def __init__(self, quarantine=None):
        self.quarantine = quarantine or DispatchQuarantine()
        self._current_revision = DispatchRevision(1, 1, "active", "1.0.0")
        self._dispatched = 0; self._rejected = 0
    @property
    def current_revision(self): return self._current_revision
    def dispatch(self, event):
        event_type = event.get("type", "")
        target_rev = DispatchRevision.from_dict(event.get("revision", {}))
        if not self.quarantine.accept(event_type, target_rev, self._current_revision):
            reason = f"unknown event type {event_type!r}" if event_type not in EventKind.known() else f"version mismatch: current={self._current_revision.version} target={target_rev.version} attempt={target_rev.attempt}"
            self.quarantine.quarantine(event, reason); self._rejected += 1; return False
        self._current_revision = target_rev; self._dispatched += 1; return True
    @property
    def dispatched(self): return self._dispatched
    @property
    def rejected(self): return self._rejected
    def __repr__(self): return f"EventDispatcher(current={self._current_revision!r}, dispatched={self._dispatched}, rejected={self._rejected})"
