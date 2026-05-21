"""Artifact upload route — enforces body size limits."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.services.artifact_service import (
    validate_artifact_size,
    store_artifact,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.post("/upload")
async def upload_artifact(
    request: Request,
    agent_id: str,
    filename: str,
):
    """Upload an artifact for the specified agent.

    Body size is validated before any processing occurs.
    Returns 413 if the body exceeds the configured limit,
    or 411 if Content-Length is missing.
    """
    # Validate body size in the shared service layer (before any mutation)
    content_length = request.headers.get("content-length")
    validate_artifact_size(
        int(content_length) if content_length else None,
    )

    # Read body (bounded by FastAPI's max_body_size, but we already checked)
    body = await request.body()

    # Store the artifact
    result = store_artifact(agent_id, filename, body)
    return result
