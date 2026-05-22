"""Custom exception definitions with consistent error codes."""

from typing import Any, Dict, Optional


class AgentOrchestratorError(Exception):
    """Base exception for all platform errors."""
    pass


class ValidationError(AgentOrchestratorError):
    """Raised when request validation fails."""
    def __init__(self, message: str, code: str = "VALIDATION_ERROR", details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.details = details or {}
        super().__init__(message)


class AgentNotFoundError(AgentOrchestratorError):
    def __init__(self, agent_id: str):
        super().__init__(f"Agent not found: {agent_id}")


class AgentTimeoutError(AgentOrchestratorError):
    def __init__(self, agent_id: str, timeout: int):
        super().__init__(f"Agent {agent_id} timed out after {timeout}s")


class TaskExecutionError(AgentOrchestratorError):
    def __init__(self, task_id: str, reason: str):
        super().__init__(f"Task {task_id} failed: {reason}")


class ConfigurationError(AgentOrchestratorError):
    def __init__(self, message: str):
        super().__init__(f"Configuration error: {message}")


class AuthenticationError(AgentOrchestratorError):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class RateLimitError(AgentOrchestratorError):
    def __init__(self, retry_after: int = 60):
        super().__init__(f"Rate limit exceeded. Retry after {retry_after}s")
        self.retry_after = retry_after


class ResourceExhaustedError(AgentOrchestratorError):
    def __init__(self, resource: str):
        super().__init__(f"Resource exhausted: {resource}")


# Standardized error codes for the public API
ERROR_CODES = {
    "VALIDATION_ERROR": "ERR_VALIDATION",
    "NOT_FOUND": "ERR_NOT_FOUND",
    "AUTHENTICATION_ERROR": "ERR_AUTHENTICATION",
    "RATE_LIMIT": "ERR_RATE_LIMIT",
    "RESOURCE_EXHAUSTED": "ERR_RESOURCE_EXHAUSTED",
    "CONFIGURATION_ERROR": "ERR_CONFIGURATION",
    "INTERNAL_ERROR": "ERR_INTERNAL",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> dict:
    """Build a consistent JSON error response body."""
    response = {
        "error": {
            "code": code,
            "message": message,
            "status_code": status_code,
        }
    }
    if details:
        response["error"]["details"] = details
    return response
