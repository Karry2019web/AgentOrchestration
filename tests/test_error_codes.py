"""Tests for consistent error codes in API routes."""

import pytest
from fastapi import HTTPException
from src.agent.registry import AgentRegistry, AgentStatus
from src.common.errors import (
    error_response,
    ERROR_CODES,
    ValidationError,
)


class TestErrorResponse:
    def test_error_response_basic(self):
        resp = error_response(422, "ERR_VALIDATION", "Invalid input")
        assert resp["error"]["code"] == "ERR_VALIDATION"
        assert resp["error"]["message"] == "Invalid input"
        assert resp["error"]["status_code"] == 422
        assert "details" not in resp["error"]

    def test_error_response_with_details(self):
        resp = error_response(422, "ERR_VALIDATION", "Invalid input", {"field": "name"})
        assert resp["error"]["details"]["field"] == "name"

    def test_error_response_all_codes(self):
        for _name, code in ERROR_CODES.items():
            resp = error_response(400, code, "test")
            assert resp["error"]["code"] == code


class TestValidationError:
    def test_validation_error_basic(self):
        err = ValidationError("Invalid name")
        assert str(err) == "Invalid name"
        assert err.code == "VALIDATION_ERROR"

    def test_validation_error_with_details(self):
        err = ValidationError("Invalid input", details={"field": "age"})
        assert err.details["field"] == "age"

    def test_validation_error_custom_code(self):
        err = ValidationError("Bad request", code="CUSTOM_ERR")
        assert err.code == "CUSTOM_ERR"


class TestRouteErrorCodes:
    """Integration-style tests for route-level error handling."""

    def test_list_agents_invalid_status_returns_422(self):
        with pytest.raises(HTTPException) as exc_info:
            from src.api.routes import list_agents
            import asyncio
            asyncio.run(list_agents(status="invalid_status"))
        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        assert detail["error"]["code"] == ERROR_CODES["VALIDATION_ERROR"]

    def test_register_agent_empty_name_returns_422(self):
        with pytest.raises(HTTPException) as exc_info:
            from src.api.routes import register_agent
            import asyncio
            asyncio.run(register_agent(name="", agent_type="worker"))
        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        assert detail["error"]["code"] == ERROR_CODES["VALIDATION_ERROR"]

    def test_register_agent_empty_type_returns_422(self):
        with pytest.raises(HTTPException) as exc_info:
            from src.api.routes import register_agent
            import asyncio
            asyncio.run(register_agent(name="test", agent_type=""))
        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        assert detail["error"]["code"] == ERROR_CODES["VALIDATION_ERROR"]

    def test_get_nonexistent_agent_returns_404(self):
        with pytest.raises(HTTPException) as exc_info:
            from src.api.routes import get_agent
            import asyncio
            asyncio.run(get_agent(agent_id="nonexistent"))
        assert exc_info.value.status_code == 404
        detail = exc_info.value.detail
        assert detail["error"]["code"] == ERROR_CODES["NOT_FOUND"]

    def test_delete_nonexistent_agent_returns_404(self):
        with pytest.raises(HTTPException) as exc_info:
            from src.api.routes import delete_agent
            import asyncio
            asyncio.run(delete_agent(agent_id="nonexistent"))
        assert exc_info.value.status_code == 404
        detail = exc_info.value.detail
        assert detail["error"]["code"] == ERROR_CODES["NOT_FOUND"]
