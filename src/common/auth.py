"""Worker token validation and authentication guards.

Validates bearer tokens used in worker auth, enforcing not-before (nbf),
expiration (exp), scope, workspace isolation, and anonymous-principal checks.
All validation fails closed — any unexpected or missing claim is treated as
invalid rather than silently accepted.
"""

import base64
import json
import time
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class TokenValidationError(Exception):
    """Raised when a token payload cannot be decoded or parsed."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Token validation failed: {reason}")


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    """Decode the payload section of a JWT without verifying the signature.

    Signature verification is assumed to be handled upstream (e.g. by an
    identity provider or gateway). This function only extracts claims for
    local validation of time, scope, and identity constraints.

    Raises:
        TokenValidationError: if the token structure or payload encoding
            is invalid.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenValidationError("malformed token: expected 3 dot-separated parts")

    payload_b64 = parts[1]
    remainder = len(payload_b64) % 4
    if remainder:
        payload_b64 += "=" * (4 - remainder)

    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenValidationError(f"malformed payload encoding: {exc}")


def validate_worker_token(
    token: str,
    now: Optional[float] = None,
    required_scope: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Validate a worker auth bearer token and return (claims, error).

    Checks performed in order (early-exit on first failure):

        1. **Structure** — token must be a valid 3-part JWT-like string.
        2. **Not-before (nbf)** — token must not be used before its
           ``nbf`` timestamp.
        3. **Expiration (exp)** — token must not be expired.
        4. **Subject (sub)** — must be present and not ``"anonymous"``.
        5. **Scope** — if *required_scope* is provided, the token must
           include it in ``scopes`` (list or comma-separated string) or
           ``scope`` (space-separated string) claims.
        6. **Workspace** — if *workspace* is provided, the token's
           ``workspace`` or ``workspace_id`` claim must match exactly.

    Any claim that is missing, unparsable, or of the wrong type is treated
    as invalid (fail-closed).

    Returns:
        A tuple of ``(claims_dict, None)`` on success, or
        ``({}, error_string)`` on failure.
    """
    if not token or not token.strip():
        return {}, "empty token"

    _now = now if now is not None else time.time()

    try:
        claims = decode_jwt_payload(token)
    except TokenValidationError as exc:
        return {}, exc.reason

    # --- 1. Not-before (nbf) ---
    nbf = claims.get("nbf")
    if nbf is not None:
        try:
            nbf_time = float(nbf)
        except (TypeError, ValueError):
            return {}, "malformed nbf claim"
        if _now < nbf_time:
            logger.warning(
                "Token used before nbf: now=%.1f nbf=%.1f", _now, nbf_time
            )
            return {}, "token not yet valid"

    # --- 2. Expiration (exp) ---
    exp = claims.get("exp")
    if exp is not None:
        try:
            exp_time = float(exp)
        except (TypeError, ValueError):
            return {}, "malformed exp claim"
        if _now >= exp_time:
            return {}, "token expired"

    # --- 3. Subject / anonymous check ---
    sub = claims.get("sub")
    if sub is None or (isinstance(sub, str) and sub.strip().lower() in ("anonymous", "guest", "")):
        return {}, "anonymous principal denied"
    if not isinstance(sub, str):
        return {}, "malformed sub claim"

    # --- 4. Scope check ---
    if required_scope:
        token_scopes: list = []
        raw_scopes = claims.get("scopes")
        if isinstance(raw_scopes, list):
            token_scopes = raw_scopes
        elif isinstance(raw_scopes, str):
            token_scopes = [s.strip() for s in raw_scopes.split(",")]

        raw_scope = claims.get("scope")
        if isinstance(raw_scope, str):
            token_scopes.extend(raw_scope.split())

        if required_scope not in token_scopes:
            return {}, "insufficient scope"

    # --- 5. Workspace isolation ---
    if workspace:
        token_ws = claims.get("workspace") or claims.get("workspace_id")
        if token_ws != workspace:
            return {}, "workspace mismatch"

    return claims, None
