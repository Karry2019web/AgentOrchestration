"""FastAPI application server."""

import os
from typing import Dict

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .routes import router
from .middleware import AuthMiddleware, RateLimitMiddleware, LoggingMiddleware

# Sensitive execution metadata keys that must be redacted from public health responses.
# These represent runtime-internal fields such as agent registry state, scheduler queue
# state, process details, or environment configuration that should not be exposed to
# unauthenticated callers or external monitoring endpoints.
_SENSITIVE_METADATA_KEYS = frozenset({
    "agent_registry",
    "scheduler_queue",
    "in_flight_tasks",
    "active_processes",
    "pid",
    "process_id",
    "hostname",
    "internal_host",
    "env",
    "environment",
    "secrets",
    "tokens",
    "api_keys",
    "private_ip",
    "internal_ip",
    "config",
    "configuration",
    "debug",
    "trace_id",
    "span_id",
    "agent_id",
    "execution_id",
    "workspace_id",
    "storage_path",
    "sandbox_path",
    "db_url",
    "database_url",
    "redis_url",
    "cache_keys",
    "internal_metrics",
    "runtime_stats",
    "worker_pids",
    "process_info",
})


def redact_execution_metadata(data: Dict) -> Dict:
    """Redact sensitive execution metadata from a public health response.

    Recursively scans *data* and removes any key that matches a known sensitive
    metadata key (case-insensitive comparison).  Returns a new dict; the original
    is not mutated.

    This is the shared service function called by every route that exposes
    internal runtime state.  Adding new sensitive keys to ``_SENSITIVE_METADATA_KEYS``
    is sufficient to keep them out of public responses.
    """
    if not isinstance(data, dict):
        return data
    safe = {}
    for key, value in data.items():
        if isinstance(key, str) and key.lower() in _SENSITIVE_METADATA_KEYS:
            continue
        if isinstance(value, dict):
            safe[key] = redact_execution_metadata(value)
        elif isinstance(value, list):
            safe[key] = [
                redact_execution_metadata(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            safe[key] = value
    return safe


def create_app(config: Dict = None) -> FastAPI:
    app = FastAPI(
        title="Agent Orchestrator API",
        version="2.4.1",
        description="Enterprise Agent Orchestration Platform API",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv("TRUSTED_HOSTS", "*").split(","))

    app.add_middleware(AuthMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(LoggingMiddleware)

    app.include_router(router, prefix="/api/v2")

    @app.get("/health")
    async def health():
        return _get_public_health()

    return app


def _get_public_health() -> Dict:
    """Build the public health response with execution metadata redacted.

    Uses ``redact_execution_metadata`` to strip any internal runtime state
    that may have been collected before serialization, ensuring the public
    endpoint never leaks sensitive operational details.
    """
    raw = {
        "status": "healthy",
        "version": "2.4.1",
    }
    return redact_execution_metadata(raw)
