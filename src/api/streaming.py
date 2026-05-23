"""SSE Streaming Service — Cursor ownership validation and streaming updates."""

import json
from typing import Any, Dict, Optional


class SSEError(Exception):
    """Base error for SSE streaming operations."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class CursorNotFoundError(SSEError):
    def __init__(self):
        super().__init__("Cursor not found", status_code=404)


class CursorOwnershipError(SSEError):
    def __init__(self):
        super().__init__(
            "Cursor does not belong to the current workspace or role",
            status_code=403,
        )


class StreamingService:
    """Shared streaming service that validates cursor ownership."""

    def __init__(self):
        self._cursors: Dict[str, Dict[str, Any]] = {}

    def create_cursor(
        self,
        workspace_id: str,
        role: str,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        import uuid
        cursor_id = str(uuid.uuid4())
        self._cursors[cursor_id] = {
            "id": cursor_id,
            "workspace_id": workspace_id,
            "role": role,
            "agent_id": agent_id,
            "metadata": metadata or {},
            "position": 0,
        }
        return cursor_id

    def get_cursor(
        self, cursor_id: str, workspace_id: str, role: str
    ) -> Dict[str, Any]:
        cursor = self._cursors.get(cursor_id)
        if cursor is None:
            raise CursorNotFoundError()
        if cursor["workspace_id"] != workspace_id or cursor["role"] != role:
            raise CursorOwnershipError()
        return cursor

    def advance_cursor(
        self, cursor_id: str, workspace_id: str, role: str, position: int
    ) -> Dict[str, Any]:
        cursor = self.get_cursor(cursor_id, workspace_id, role)
        cursor["position"] = position
        return cursor

    def delete_cursor(
        self, cursor_id: str, workspace_id: str, role: str
    ) -> None:
        self.get_cursor(cursor_id, workspace_id, role)
        self._cursors.pop(cursor_id, None)

    def list_cursors(self, workspace_id: str, role: str) -> list:
        return [
            c
            for c in self._cursors.values()
            if c["workspace_id"] == workspace_id and c["role"] == role
        ]


# Singleton instance
streaming_service = StreamingService()
