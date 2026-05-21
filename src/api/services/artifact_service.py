"""Artifact ingestion service with body size validation."""

import logging
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Default max body size: 10 MB
DEFAULT_MAX_ARTIFACT_SIZE = 10 * 1024 * 1024


def validate_artifact_size(
    content_length: Optional[int],
    max_size: int = DEFAULT_MAX_ARTIFACT_SIZE,
) -> None:
    """Validate artifact upload body size before any processing.

    This guard is called from the shared service layer so that all
    artifact ingestion paths enforce size limits consistently.

    Args:
        content_length: The Content-Length header value, or None if not sent.
        max_size: Maximum allowed body size in bytes (default 10 MB).

    Raises:
        HTTPException 413 if the body exceeds the limit.
        HTTPException 411 if Content-Length is missing.
    """
    if content_length is None:
        raise HTTPException(
            status_code=411,
            detail="Content-Length header is required for artifact upload",
        )

    if content_length > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"Artifact size {content_length} bytes exceeds maximum "
                   f"allowed size of {max_size} bytes",
        )

    logger.debug("Artifact size %d bytes within limit (%d bytes)", content_length, max_size)


def store_artifact(agent_id: str, filename: str, content: bytes) -> dict:
    """Store an artifact for the given agent.

    This is a placeholder for the actual storage implementation.
    The function exists so that the body-size guard lives in the
    shared service layer (per the bounty requirement).

    Returns:
        A dict with artifact metadata.
    """
    artifact_id = f"{agent_id}/{filename}"
    logger.info("Artifact %s stored (%d bytes)", artifact_id, len(content))
    return {
        "artifact_id": artifact_id,
        "agent_id": agent_id,
        "filename": filename,
        "size_bytes": len(content),
        "status": "stored",
    }
