"""Worker authentication utilities."""

import time
import json
import base64
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Base authentication error."""


class MalformedTokenError(AuthError):
    """Token is structurally invalid."""


class TokenNotYetValidError(AuthError):
    """Token nbf (not-before) is in the future."""


class TokenExpiredError(AuthError):
    """Token has expired."""


class InvalidSubjectError(AuthError):
    """Token subject is anonymous, empty, or invalid."""


class InsufficientScopeError(AuthError):
    """Token lacks the required scope."""


class WorkspaceMismatchError(AuthError):
    """Token workspace does not match request workspace."""


def decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    """Decode a JWT payload without signature verification.

    Returns the payload dict or None if decoding fails.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError, IndexError, TypeError):
        return None


def validate_worker_token(
    token: str,
    required_scope: str = "worker",
    workspace_id: Optional[str] = None,
    max_clock_skew: int = 30,
) -> Dict[str, Any]:
    """Validate a worker authentication bearer token.

    Performs the following checks in order:
    1. Structural validity (3-part JWT)
    2. nbf (not-before) claim - must not be in the future
    3. exp (expiry) claim - must not be in the past
    4. Subject (sub) claim - must be present and non-empty
    5. Scope claim - must contain required_scope
    6. Workspace claim - must match workspace_id if provided

    Args:
        token: Bearer token string.
        required_scope: Scope required for access.
        workspace_id: Expected workspace ID (optional).
        max_clock_skew: Maximum allowed clock skew in seconds.

    Returns:
        Decoded token claims dict on success.

    Raises:
        MalformedTokenError: Token is not a valid 3-part JWT.
        TokenNotYetValidError: nbf is in the future.
        TokenExpiredError: Token has expired.
        InvalidSubjectError: Subject is missing, empty, or anonymous.
        InsufficientScopeError: Required scope not found.
        WorkspaceMismatchError: Workspace does not match.
    """
    if not token or not token.startswith("Bearer "):
        raise MalformedTokenError("Missing or malformed Authorization header")

    jwt_token = token[len("Bearer "):].strip()
    if not jwt_token:
        raise MalformedTokenError("Empty token")

    payload = decode_jwt_payload(jwt_token)
    if payload is None:
        raise MalformedTokenError("Unable to decode JWT payload")

    now = time.time()

    # Check nbf (not-before)
    nbf = payload.get("nbf")
    if nbf is not None:
        if isinstance(nbf, (int, float)) and nbf > now + max_clock_skew:
            raise TokenNotYetValidError(
                f"Token not-before time ({nbf}) is in the future"
            )

    # Check exp (expiry)
    exp = payload.get("exp")
    if exp is not None:
        if isinstance(exp, (int, float)) and exp < now - max_clock_skew:
            raise TokenExpiredError(f"Token expired at {exp}")

    # Check subject
    sub = payload.get("sub")
    if not sub or sub in ("anonymous", "guest", "", "anon"):
        raise InvalidSubjectError(
            f"Invalid token subject: {sub!r}"
        )

    # Check scope
    scope = payload.get("scope", "")
    if required_scope and required_scope not in str(scope).split():
        raise InsufficientScopeError(
            f"Token missing required scope: {required_scope}"
        )

    # Check workspace
    if workspace_id is not None:
        token_workspace = payload.get("workspace_id") or payload.get("workspace")
        if token_workspace != workspace_id:
            raise WorkspaceMismatchError(
                f"Token workspace {token_workspace!r} does not match "
                f"request workspace {workspace_id!r}"
            )

    return payload

# 2026-05-24T08:00:00Z update
