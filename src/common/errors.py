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


class IncompatibleProtocolError(AgentOrchestratorError):
    """Raised when an agent's protocol version is incompatible."""

    def __init__(self, agent_id: str, agent_version: str, system_version: str):
        self.agent_id = agent_id
        self.agent_version = agent_version
        self.system_version = system_version
        super().__init__(
            f"Agent {agent_id} protocol version {agent_version} "
            f"is incompatible with system version {system_version}"
        )


class ProtocolNegotiationError(AgentOrchestratorError):
    """Raised when protocol negotiation fails for reasons other than version mismatch."""

    def __init__(self, agent_id: str, version: str, reason: str):
        self.agent_id = agent_id
        self.version = version
        super().__init__(
            f"Protocol negotiation failed for agent {agent_id} "
            f"with version '{version}': {reason}"
        )
