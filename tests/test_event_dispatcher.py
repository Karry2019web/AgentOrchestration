"""Deterministic regression tests for orchestrator event dispatcher quarantine."""
import pytest
from src.orchestrator.dispatcher import DispatchQuarantine, DispatchRevision, EventDispatcher, EventKind

class TestEventKind:
    def test_known_contains_all(self):
        known = EventKind.known()
        for ek in EventKind:
            assert ek.value in known
    def test_unknown_not_known(self):
        assert "nonsense.event" not in EventKind.known()
        assert "" not in EventKind.known()

class TestDispatchRevision:
    def test_same_version_increasing_allowed(self):
        c = DispatchRevision(revision=5, version="2.0.0")
        t = DispatchRevision(revision=6, version="2.0.0")
        assert t.allows(c)
    def test_same_version_equal_rejected(self):
        c = DispatchRevision(revision=5, version="2.0.0")
        t = DispatchRevision(revision=5, version="2.0.0")
        assert not t.allows(c)
    def test_same_version_decreasing_rejected(self):
        c = DispatchRevision(revision=5, version="2.0.0")
        t = DispatchRevision(revision=4, version="2.0.0")
        assert not t.allows(c)
    def test_cross_version_active_first_attempt_allowed(self):
        c = DispatchRevision(revision=5, phase="active", version="2.0.0")
        t = DispatchRevision(attempt=1, revision=1, phase="active", version="3.0.0")
        assert t.allows(c)
    def test_cross_version_retry_rejected(self):
        c = DispatchRevision(revision=5, phase="active", version="2.0.0")
        t = DispatchRevision(attempt=2, revision=1, phase="active", version="3.0.0")
        assert not t.allows(c)
    def test_cross_version_inactive_phase_rejected(self):
        c = DispatchRevision(revision=5, phase="paused", version="2.0.0")
        t = DispatchRevision(attempt=1, revision=1, phase="active", version="3.0.0")
        assert not t.allows(c)
    def test_round_trip(self):
        r = DispatchRevision(attempt=3, revision=7, phase="active", version="4.0.0")
        d = r.to_dict(); r2 = DispatchRevision.from_dict(d)
        assert r2.attempt == 3 and r2.revision == 7 and r2.phase == "active" and r2.version == "4.0.0"

class TestDispatchQuarantine:
    def setup_method(self): self.q = DispatchQuarantine()
    def test_accepts_known_same_version(self):
        t = DispatchRevision(revision=2, version="1.0.0"); c = DispatchRevision(revision=1, version="1.0.0")
        assert self.q.accept("task.submitted", t, c)
    def test_rejects_unknown_type(self):
        t = DispatchRevision(revision=2, version="1.0.0"); c = DispatchRevision(revision=1, version="1.0.0")
        assert not self.q.accept("completely.unknown", t, c)
    def test_rejects_stale_revision(self):
        t = DispatchRevision(revision=1, version="1.0.0"); c = DispatchRevision(revision=5, version="1.0.0")
        assert not self.q.accept("task.submitted", t, c)
    def test_quarantine_records(self):
        self.q.quarantine({"id": "abc"}, "test reason")
        assert self.q.count == 1 and len(self.q.records) == 1
    def test_reset_clears(self):
        self.q.quarantine({"id": "x"}, "test"); self.q.reset()
        assert self.q.count == 0 and len(self.q.records) == 0
    def test_register_new_type(self):
        self.q.register("custom.event")
        t = DispatchRevision(revision=2, version="1.0.0"); c = DispatchRevision(revision=1, version="1.0.0")
        assert self.q.accept("custom.event", t, c)

class TestEventDispatcher:
    def test_dispatch_known_event(self):
        d = EventDispatcher()
        ok = d.dispatch({"type": "task.submitted", "revision": {"revision": 2, "version": "1.0.0"}})
        assert ok and d.dispatched == 1 and d.rejected == 0 and d.quarantine.count == 0
    def test_reject_unknown_event(self):
        d = EventDispatcher()
        ok = d.dispatch({"type": "bogus.event", "revision": {"revision": 2, "version": "1.0.0"}})
        assert not ok and d.dispatched == 0 and d.rejected == 1 and d.quarantine.count == 1
    def test_reject_stale_event(self):
        d = EventDispatcher()
        d.dispatch({"type": "task.submitted", "revision": {"revision": 5, "version": "1.0.0"}})
        ok = d.dispatch({"type": "task.submitted", "revision": {"revision": 3, "version": "1.0.0"}})
        assert not ok and d.dispatched == 1 and d.rejected == 1

class TestRollingUpgrade:
    def test_quarantine_unknown_during_upgrade(self):
        d = EventDispatcher()
        ok = d.dispatch({"type": "task.new_version_event", "revision": {"attempt": 1, "revision": 1, "phase": "active", "version": "2.0.0"}})
        assert not ok and d.quarantine.count == 1
    def test_quarantine_retry_during_upgrade(self):
        d = EventDispatcher()
        ok = d.dispatch({"type": "task.submitted", "revision": {"attempt": 2, "revision": 1, "phase": "active", "version": "2.0.0"}})
        assert not ok
    def test_preserves_current_revision_after_quarantine(self):
        d = EventDispatcher()
        before = (d.current_revision.revision, d.current_revision.version)
        d.dispatch({"type": "unknown.event", "revision": {"revision": 99, "version": "9.9.9"}})
        after = (d.current_revision.revision, d.current_revision.version)
        assert before == after
