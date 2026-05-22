"""Custom exception definitions."""


class AgentOrchestratorError(Exception):
    """Base exception for all platform errors."""
    pass


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


class TenantOwnershipError(AgentOrchestratorError):
    """Raised when an event's tenant does not match the target agent or run tenant."""
    def __init__(self, event_tenant: str, expected_tenant: str):
        super().__init__(
            f"Event tenant '{event_tenant}' does not match expected tenant '{expected_tenant}'"
        )
        self.event_tenant = event_tenant
        self.expected_tenant = expected_tenant


class StaleEventError(AgentOrchestratorError):
    """Raised when a stale or duplicate event is received."""
    def __init__(self, event_id: str, current_revision: int):
        super().__init__(
            f"Stale or duplicate event {event_id} at revision {current_revision}"
        )
        self.event_id = event_id
        self.current_revision = current_revision
