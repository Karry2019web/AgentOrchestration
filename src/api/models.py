"""API response models with admin-only field enforcement."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RunMetrics(BaseModel):
    """Agent run performance metrics."""
    tasks_completed: int = 0
    errors: int = 0
    uptime: float = 0.0


class RunDetailPublic(BaseModel):
    """Public run detail — safe for all authenticated users."""
    id: str
    name: str
    agent_type: str
    status: str
    created_at: float
    updated_at: float
    metrics: RunMetrics = Field(default_factory=RunMetrics)


class RunDetailAdmin(RunDetailPublic):
    """Admin run detail — includes sensitive infra fields."""
    host: Optional[str] = None
    container_id: Optional[str] = None
    ip_address: Optional[str] = None
    environment_vars: Dict[str, str] = Field(default_factory=dict)
    log_path: Optional[str] = None
    token_id: Optional[str] = None


def enforce_admin_fields(run_data: Dict[str, Any], is_admin: bool) -> Dict[str, Any]:
    """Strip admin-only fields unless the caller has admin privileges.

    Admin-only fields: host, container_id, ip_address, environment_vars,
    log_path, token_id.
    """
    if is_admin:
        return run_data

    admin_only = {"host", "container_id", "ip_address", "environment_vars",
                  "log_path", "token_id"}
    return {k: v for k, v in run_data.items() if k not in admin_only}


def require_admin_role(role: Optional[str]) -> bool:
    """Check whether the given role qualifies as admin."""
    return role is not None and role.lower() in ("admin", "owner", "superuser")
