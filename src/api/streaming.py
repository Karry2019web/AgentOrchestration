"""SSE Streaming Service — Validates cursor ownership and manages streaming sessions."""

from typing import Optional, Dict, Any
from uuid import UUID
from src.agent.registry import AgentRegistry
from src.common.errors import AuthenticationError


class SSECursor:
    """Represents an SSE cursor (event stream position marker) tied to a workspace and role."""

    def __init__(self, cursor_id: str, workspace_id: str, role: str, agent_id: str):
        self.cursor_id = cursor_id
        self.workspace_id = workspace_id
        self.role = role
        self.agent_id = agent_id

    def __repr__(self):
        return f"SSECursor(cursor_id={self.cursor_id}, workspace_id={self.workspace_id}, role={self.role})"


class StreamingService:
    """Manages SSE streaming sessions with workspace-scoped cursor ownership validation."""

    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        self._sessions: Dict[str, SSECursor] = {}

    def validate_cursor_ownership(
        self,
        cursor_id: str,
        workspace_id: str,
        role: str,
        agent_id: Optional[str] = None,
    ) -> SSECursor:
        """Validate that the cursor belongs to the caller's workspace and role.

        Returns the validated SSECursor or raises a 4xx-equivalent error.

        Args:
            cursor_id: The SSE cursor/position ID to validate.
            workspace_id: The caller's authenticated workspace.
            role: The caller's active role.
            agent_id: Optional agent ID for additional scope validation.

        Returns:
            SSECursor: The validated cursor object.

        Raises:
            ValueError: If cursor_id is blank or malformed.
            PermissionError: If the cursor does not belong to the given workspace/role.
        """
        # Validate inputs before any lookup
        if not cursor_id or not cursor_id.strip():
            raise ValueError("Cursor ID must not be blank")

        if not workspace_id or not workspace_id.strip():
            raise ValueError("Workspace ID must not be blank")

        if not role or not role.strip():
            raise ValueError("Role must not be blank")

        # Validate cursor format (must be a valid UUID)
        try:
            UUID(cursor_id)
        except (ValueError, AttributeError):
            raise ValueError(f"Malformed cursor ID: {cursor_id}")

        # Attempt to retrieve the cursor session
        cursor = self._sessions.get(cursor_id)

        if cursor is None:
            # Even if cursor doesn't exist, don't reveal that — return a generic error
            raise PermissionError(
                f"Cursor {cursor_id} not accessible in workspace {workspace_id}"
            )

        # Scoped ownership check: cursor must belong to the same workspace AND role
        if cursor.workspace_id != workspace_id:
            raise PermissionError(
                f"Cursor {cursor_id} not accessible in workspace {workspace_id}"
            )

        if cursor.role != role:
            raise PermissionError(
                f"Cursor {cursor_id} not accessible with role {role}"
            )

        # Optional: validate agent ownership if agent_id is provided
        if agent_id is not None:
            agent = self.registry.get(agent_id)
            if agent is None:
                raise ValueError(f"Agent {agent_id} not found")
            if cursor.agent_id != agent_id:
                raise PermissionError(
                    f"Cursor {cursor_id} not owned by agent {agent_id}"
                )

        return cursor

    def create_cursor(self, workspace_id: str, role: str, agent_id: str) -> SSECursor:
        """Create a new SSE cursor tied to a specific workspace and role."""
        import uuid
        cursor_id = str(uuid.uuid4())
        cursor = SSECursor(
            cursor_id=cursor_id,
            workspace_id=workspace_id,
            role=role,
            agent_id=agent_id,
        )
        self._sessions[cursor_id] = cursor
        return cursor

    def delete_cursor(self, cursor_id: str) -> bool:
        """Remove a cursor session."""
        return self._sessions.pop(cursor_id, None) is not None
