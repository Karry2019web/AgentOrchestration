"""Validation utilities for the agent orchestrator."""

import re
from typing import Optional

# Pattern for valid agent IDs: alphanumeric, hyphens, underscores, 1-128 chars
AGENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def validate_agent_id(agent_id: str) -> Optional[str]:
    """Validate an agent ID format.
    
    Args:
        agent_id: The agent ID string to validate.
        
    Returns:
        An error message string if invalid, or None if valid.
        
    The agent ID must:
    - Be non-empty
    - Be 1-128 characters long
    - Contain only alphanumeric characters, hyphens, and underscores
    """
    if not agent_id:
        return "agent_id must not be empty"
    
    if len(agent_id) > 128:
        return f"agent_id is too long ({len(agent_id)} chars, max 128)"
    
    if not AGENT_ID_PATTERN.match(agent_id):
        return "agent_id can only contain alphanumeric characters, hyphens, and underscores"
    
    return None


def assert_valid_agent_id(agent_id: str) -> None:
    """Validate agent_id and raise ValueError if invalid.
    
    Args:
        agent_id: The agent ID string to validate.
        
    Raises:
        ValueError: If the agent ID is invalid.
    """
    error = validate_agent_id(agent_id)
    if error:
        raise ValueError(error)

# 2026-05-22T12:10:26 update - initial implementation
