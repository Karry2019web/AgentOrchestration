"""Tests for tenant ownership validation on shared event bus."""

import pytest
from src.orchestrator.engine import EventBus, EventRecord, OrchestrationEngine
from src.common.errors import TenantOwnershipError, StaleEventError


class TestEventBus:
    """Regression test suite for shared event bus tenant ownership."""

    def setup_method(self):
        self.bus = EventBus()

    def _make_event(self, tenant_id="tenant-alpha", source="agent-1",
                    revision=1, event_type="lifecycle_transition",
                    target_status="enqueued"):
        return EventRecord(
            event_type=event_type,
            tenant_id=tenant_id,
            source=source,
            revision=revision,
            payload={"target_status": target_status},
        )

    # -- Tenant ownership validation --

    def test_accept_correct_tenant(self):
        """An event from the correct tenant is accepted."""
        event = self._make_event()
        result = self.bus.accept_event(event, "tenant-alpha")
        assert result["accepted"] is True
        assert result["reason"] == "ok"

    def test_reject_wrong_tenant(self):
        """An event from a non-matching tenant is rejected."""
        event = self._make_event(tenant_id="tenant-intruder")
        result = self.bus.accept_event(event, "tenant-alpha")
        assert result["accepted"] is False
        assert "does not match" in result["reason"]

    # -- Revision monotonicity --

    def test_reject_stale_event(self):
        """A stale event with non-increasing revision is rejected."""
        self.bus.accept_event(self._make_event(revision=5), "tenant-alpha")
        result = self.bus.accept_event(self._make_event(revision=3), "tenant-alpha")
        assert result["accepted"] is False
        assert "stale" in result["reason"].lower()

    def test_accept_monotonic_revision(self):
        """Events with strictly increasing revisions are accepted."""
        self.bus.accept_event(self._make_event(revision=1), "tenant-alpha")
        result = self.bus.accept_event(self._make_event(revision=2), "tenant-alpha")
        assert result["accepted"] is True

    # -- Lifecycle transition validation --

    def test_valid_lifecycle_transition_pending_to_enqueued(self):
        """pending -> enqueued is a valid transition."""
        event = self._make_event(target_status="enqueued")
        result = self.bus.accept_event(event, "tenant-alpha")
        assert result["accepted"] is True
        assert result["new_state"] == "enqueued"

    def test_valid_lifecycle_transition_enqueued_to_in_flight(self):
        """enqueued -> in_flight is a valid transition."""
        self.bus.accept_event(self._make_event(revision=1, target_status="enqueued"), "tenant-alpha")
        result = self.bus.accept_event(
            self._make_event(revision=2, source="agent-1", target_status="in_flight"),
            "tenant-alpha",
        )
        assert result["accepted"] is True
        assert result["new_state"] == "in_flight"

    def test_invalid_lifecycle_transition(self):
        """pending -> completed directly (skipping enqueued/in_flight) is rejected."""
        event = self._make_event(target_status="completed")
        result = self.bus.accept_event(event, "tenant-alpha")
        assert result["accepted"] is False
        assert result["current_state"] == "pending"

    def test_completed_is_terminal(self):
        """A completed state cannot transition to in_flight."""
        self.bus.accept_event(self._make_event(revision=1, target_status="enqueued"), "tenant-alpha")
        self.bus.accept_event(self._make_event(revision=2, target_status="in_flight"), "tenant-alpha")
        self.bus.accept_event(self._make_event(revision=3, target_status="completed"), "tenant-alpha")
        result = self.bus.accept_event(
            self._make_event(revision=4, target_status="in_flight"),
            "tenant-alpha",
        )
        assert result["accepted"] is False

    # -- State management --

    def test_get_state(self):
        """get_state returns the current lifecycle state."""
        self.bus.accept_event(self._make_event(revision=1), "tenant-alpha")
        state = self.bus.get_state("tenant-alpha", "agent-1")
        assert state is not None
        assert state.tenant_id == "tenant-alpha"
        assert state.agent_id == "agent-1"

    def test_get_state_unknown_returns_none(self):
        """get_state for an unknown tenant-agent returns None."""
        state = self.bus.get_state("unknown", "ghost")
        assert state is None

    def test_reset_state(self):
        """reset_state clears the lifecycle state."""
        self.bus.accept_event(self._make_event(revision=1), "tenant-alpha")
        self.bus.reset_state("tenant-alpha", "agent-1")
        state = self.bus.get_state("tenant-alpha", "agent-1")
        assert state is None

    # -- Multi-tenant isolation --

    def test_independent_tenant_states(self):
        """Two tenants can have independent lifecycle progress."""
        self.bus.accept_event(
            self._make_event(tenant_id="tenant-a", source="agent-a", revision=1, target_status="enqueued"),
            "tenant-a",
        )
        self.bus.accept_event(
            self._make_event(tenant_id="tenant-b", source="agent-b", revision=1, target_status="enqueued"),
            "tenant-b",
        )
        self.bus.accept_event(
            self._make_event(tenant_id="tenant-b", source="agent-b", revision=2, target_status="in_flight"),
            "tenant-b",
        )

        a_state = self.bus.get_state("tenant-a", "agent-a")
        b_state = self.bus.get_state("tenant-b", "agent-b")
        assert a_state.status == "enqueued"
        assert b_state.status == "in_flight"


class TestOrchestrationEngineEventDispatch:
    """Tests for OrchestrationEngine.dispatch_event integration."""

    def setup_method(self):
        self.engine = OrchestrationEngine()
        # Register an agent with a tenant
        agent = {"id": "agent-1", "name": "Test Agent", "tenant_id": "tenant-alpha"}
        self.engine.registry.register(agent)

    def test_dispatch_valid_event(self):
        """A valid event from a registered agent is accepted."""
        event = EventRecord(
            event_type="lifecycle_transition",
            tenant_id="tenant-alpha",
            source="agent-1",
            revision=1,
            payload={"target_status": "enqueued"},
        )
        result = self.engine.dispatch_event(event)
        assert result["accepted"] is True

    def test_dispatch_wrong_tenant_event(self):
        """An event from a wrong tenant is rejected through dispatch_event."""
        event = EventRecord(
            event_type="lifecycle_transition",
            tenant_id="tenant-intruder",
            source="agent-1",
            revision=1,
            payload={},
        )
        result = self.engine.dispatch_event(event)
        assert result["accepted"] is False
        assert "does not match" in result["reason"]

    def test_dispatch_unregistered_agent(self):
        """An event for an unregistered agent is safely deferred."""
        event = EventRecord(
            event_type="lifecycle_transition",
            tenant_id="tenant-alpha",
            source="agent-unknown",
            revision=1,
            payload={},
        )
        result = self.engine.dispatch_event(event)
        assert result["accepted"] is False
        assert "not found" in result["reason"]
