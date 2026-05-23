"""Tests for SSE streaming cursor ownership validation."""

import pytest
from src.api.streaming import (
    streaming_service,
    StreamingService,
    CursorNotFoundError,
    CursorOwnershipError,
)


class TestStreamingService:
    def setup_method(self):
        self.service = StreamingService()

    def test_create_cursor(self):
        cursor_id = self.service.create_cursor("ws-1", "admin", "agent-1")
        assert cursor_id is not None
        cursor = self.service.get_cursor(cursor_id, "ws-1", "admin")
        assert cursor["workspace_id"] == "ws-1"
        assert cursor["role"] == "admin"
        assert cursor["agent_id"] == "agent-1"
        assert cursor["position"] == 0

    def test_get_cursor_authorized(self):
        cursor_id = self.service.create_cursor("ws-1", "admin", "agent-1")
        cursor = self.service.get_cursor(cursor_id, "ws-1", "admin")
        assert cursor["id"] == cursor_id

    def test_get_cursor_not_found(self):
        with pytest.raises(CursorNotFoundError):
            self.service.get_cursor("nonexistent", "ws-1", "admin")

    def test_get_cursor_wrong_workspace(self):
        cursor_id = self.service.create_cursor("ws-1", "admin", "agent-1")
        with pytest.raises(CursorOwnershipError):
            self.service.get_cursor(cursor_id, "ws-2", "admin")

    def test_get_cursor_wrong_role(self):
        cursor_id = self.service.create_cursor("ws-1", "admin", "agent-1")
        with pytest.raises(CursorOwnershipError):
            self.service.get_cursor(cursor_id, "ws-1", "viewer")

    def test_advance_cursor(self):
        cursor_id = self.service.create_cursor("ws-1", "admin", "agent-1")
        self.service.advance_cursor(cursor_id, "ws-1", "admin", 42)
        cursor = self.service.get_cursor(cursor_id, "ws-1", "admin")
        assert cursor["position"] == 42

    def test_advance_cursor_wrong_workspace(self):
        cursor_id = self.service.create_cursor("ws-1", "admin", "agent-1")
        with pytest.raises(CursorOwnershipError):
            self.service.advance_cursor(cursor_id, "ws-2", "admin", 42)

    def test_delete_cursor(self):
        cursor_id = self.service.create_cursor("ws-1", "admin", "agent-1")
        self.service.delete_cursor(cursor_id, "ws-1", "admin")
        with pytest.raises(CursorNotFoundError):
            self.service.get_cursor(cursor_id, "ws-1", "admin")

    def test_delete_cursor_wrong_workspace(self):
        cursor_id = self.service.create_cursor("ws-1", "admin", "agent-1")
        with pytest.raises(CursorOwnershipError):
            self.service.delete_cursor(cursor_id, "ws-2", "admin")

    def test_list_cursors(self):
        self.service.create_cursor("ws-1", "admin", "agent-1")
        self.service.create_cursor("ws-1", "admin", "agent-2")
        self.service.create_cursor("ws-2", "admin", "agent-3")
        cursors = self.service.list_cursors("ws-1", "admin")
        assert len(cursors) == 2

    def test_cursor_with_metadata(self):
        cursor_id = self.service.create_cursor(
            "ws-1", "admin", "agent-1", {"source": "test"}
        )
        cursor = self.service.get_cursor(cursor_id, "ws-1", "admin")
        assert cursor["metadata"]["source"] == "test"

    def test_singleton_instance(self):
        from src.api.streaming import streaming_service
        assert streaming_service is not None
