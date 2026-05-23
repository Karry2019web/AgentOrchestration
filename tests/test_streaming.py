"""Tests for SSE cursor ownership validation."""

import uuid
import pytest
from src.agent.registry import AgentRegistry, AgentStatus
from src.api.streaming import StreamingService, SSECursor


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest.fixture
def streaming(registry):
    return StreamingService(registry)


@pytest.fixture
def sample_cursor(streaming, registry):
    """Create a sample cursor for testing with an agent registered in the registry."""
    registry.register("test-agent", "worker.processor")
    # First registered agent gets id like ... find it
    agents = registry.list()
    agent_id = agents[0]["id"]
    return streaming.create_cursor(
        workspace_id="workspace-alpha",
        role="admin",
        agent_id=agent_id,
    )


class TestStreamingService:
    """Unit tests for StreamingService cursor ownership validation."""

    def test_create_cursor(self, streaming):
        """Verify cursor creation returns a valid SSECursor."""
        cursor = streaming.create_cursor(
            workspace_id="workspace-alpha",
            role="admin",
            agent_id="agent-001",
        )
        assert cursor is not None
        assert cursor.cursor_id is not None
        assert isinstance(uuid.UUID(cursor.cursor_id), uuid.UUID)
        assert cursor.workspace_id == "workspace-alpha"
        assert cursor.role == "admin"
        assert cursor.agent_id == "agent-001"

    def test_validate_cursor_ownership_success(self, streaming, sample_cursor):
        """Verify that a valid cursor belonging to the correct workspace/role passes."""
        cursor = streaming.validate_cursor_ownership(
            cursor_id=sample_cursor.cursor_id,
            workspace_id="workspace-alpha",
            role="admin",
        )
        assert cursor is not None
        assert cursor.cursor_id == sample_cursor.cursor_id
        assert cursor.workspace_id == "workspace-alpha"
        assert cursor.role == "admin"

    def test_validate_cursor_ownership_wrong_workspace(self, streaming, sample_cursor):
        """Verify that a cursor from workspace-alpha fails for workspace-beta."""
        with pytest.raises(PermissionError) as exc_info:
            streaming.validate_cursor_ownership(
                cursor_id=sample_cursor.cursor_id,
                workspace_id="workspace-beta",
                role="admin",
            )
        assert "not accessible in workspace" in str(exc_info.value)

    def test_validate_cursor_ownership_wrong_role(self, streaming, sample_cursor):
        """Verify that an admin cursor fails for viewer role."""
        with pytest.raises(PermissionError) as exc_info:
            streaming.validate_cursor_ownership(
                cursor_id=sample_cursor.cursor_id,
                workspace_id="workspace-alpha",
                role="viewer",
            )
        assert "not accessible with role" in str(exc_info.value)

    def test_validate_cursor_blank_cursor_id(self, streaming):
        """Verify that a blank cursor_id raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            streaming.validate_cursor_ownership(
                cursor_id="",
                workspace_id="workspace-alpha",
                role="admin",
            )
        assert "must not be blank" in str(exc_info.value)

    def test_validate_cursor_blank_workspace(self, streaming, sample_cursor):
        """Verify that a blank workspace_id raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            streaming.validate_cursor_ownership(
                cursor_id=sample_cursor.cursor_id,
                workspace_id="",
                role="admin",
            )
        assert "must not be blank" in str(exc_info.value)

    def test_validate_cursor_blank_role(self, streaming, sample_cursor):
        """Verify that a blank role raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            streaming.validate_cursor_ownership(
                cursor_id=sample_cursor.cursor_id,
                workspace_id="workspace-alpha",
                role="",
            )
        assert "must not be blank" in str(exc_info.value)

    def test_validate_malformed_cursor_id(self, streaming):
        """Verify that a non-UUID cursor_id raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            streaming.validate_cursor_ownership(
                cursor_id="not-a-valid-uuid",
                workspace_id="workspace-alpha",
                role="admin",
            )
        assert "Malformed cursor" in str(exc_info.value)

    def test_validate_nonexistent_cursor(self, streaming):
        """Verify that a valid UUID but nonexistent cursor raises PermissionError."""
        fake_id = str(uuid.uuid4())
        with pytest.raises(PermissionError) as exc_info:
            streaming.validate_cursor_ownership(
                cursor_id=fake_id,
                workspace_id="workspace-alpha",
                role="admin",
            )
        assert "not accessible" in str(exc_info.value)

    def test_validate_with_agent_id_match(self, streaming, sample_cursor, registry):
        """Verify cursor validation passes with matching agent_id."""
        agents = registry.list()
        agent_id = agents[0]["id"]
        cursor = streaming.validate_cursor_ownership(
            cursor_id=sample_cursor.cursor_id,
            workspace_id="workspace-alpha",
            role="admin",
            agent_id=agent_id,
        )
        assert cursor is not None
        assert cursor.agent_id == agent_id

    def test_validate_with_agent_id_mismatch(self, streaming, sample_cursor, registry):
        """Verify cursor validation fails with mismatched agent_id."""
        registry.register("other-agent", "worker.processor")
        other_agents = registry.list()
        other_id = other_agents[-1]["id"]
        with pytest.raises(PermissionError) as exc_info:
            streaming.validate_cursor_ownership(
                cursor_id=sample_cursor.cursor_id,
                workspace_id="workspace-alpha",
                role="admin",
                agent_id=other_id,
            )
        assert "not owned by agent" in str(exc_info.value)

    def test_delete_cursor(self, streaming, sample_cursor):
        """Verify cursor deletion removes the cursor from tracking."""
        assert streaming.delete_cursor(sample_cursor.cursor_id) is True
        # After deletion, validate should fail
        with pytest.raises(PermissionError):
            streaming.validate_cursor_ownership(
                cursor_id=sample_cursor.cursor_id,
                workspace_id="workspace-alpha",
                role="admin",
            )

    def test_delete_nonexistent_cursor(self, streaming):
        """Verify deleting a nonexistent cursor returns False."""
        assert streaming.delete_cursor(str(uuid.uuid4())) is False

    def test_validate_cursor_returns_deterministic_4xx(self, streaming):
        """Verify that invalid cursors return PermissionError (mapped to 403)
        without performing protected lookup or mutation."""
        fake_id = str(uuid.uuid4())
        with pytest.raises(PermissionError):
            streaming.validate_cursor_ownership(
                cursor_id=fake_id,
                workspace_id="workspace-alpha",
                role="admin",
            )
        # Verify no cursor was created as a side effect
        assert streaming.delete_cursor(fake_id) is False
