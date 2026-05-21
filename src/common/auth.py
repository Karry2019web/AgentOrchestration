"""JWT authentication utilities for service-to-service calls.

Provides token creation, validation and audience enforcement
for agent worker service-to-service authentication.
"""

import os
import time
import json
import hmac
import hashlib
import base64
from typing import Any, Dict, Optional, Tuple


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _get_secret_key() -> str:
    """Retrieve the shared secret for JWT signing."""
    return os.getenv("AO_JWT_SECRET", "dev-secret-do-not-use-in-prod")


def create_service_token(
    service_name: str,
    audience: str = "agent-orchestrator",
    expiry: int = 3600,
    secret: Optional[str] = None,
) -> str:
    """Create a service-to-service JWT token.

    Args:
        service_name: The name of the calling service.
        audience: The intended audience (target service).
        expiry: Token lifetime in seconds (default 1 hour).
        secret: HMAC signing secret. Falls back to AO_JWT_SECRET env.

    Returns:
        A signed JWT string.
    """
    secret = secret or _get_secret_key()
    now = int(time.time())

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": service_name,
        "aud": audience,
        "iat": now,
        "exp": now + expiry,
        "sub": f"service:{service_name}",
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())

    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{signing_input}.{sig_b64}"


def validate_service_token(
    token: str,
    expected_audience: str = "agent-orchestrator",
    allowed_issuers: Optional[list] = None,
    leeway: int = 30,
    secret: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Validate a service-to-service JWT token.

    Args:
        token: The JWT string to validate.
        expected_audience: The audience this service expects.
        allowed_issuers: List of permitted issuer names. None = any issuer.
        leeway: Clock skew tolerance in seconds.
        secret: HMAC signing secret. Falls back to AO_JWT_SECRET env.

    Returns:
        (is_valid, error_reason, payload)
    """
    secret = secret or _get_secret_key()

    # Check structure
    parts = token.split(".")
    if len(parts) != 3:
        return False, "Malformed token: expected 3 parts", None

    header_b64, payload_b64, sig_b64 = parts

    # Verify signature
    signing_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_sig_b64 = _b64url_encode(expected_sig)

    # Constant-time comparison
    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        return False, "Invalid token signature", None

    # Decode payload
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (json.JSONDecodeError, ValueError):
        return False, "Invalid token payload encoding", None

    now = time.time()

    # Check expiry
    exp = payload.get("exp")
    if exp and now > exp + leeway:
        return False, "Token has expired", payload

    # Check not-before
    nbf = payload.get("nbf")
    if nbf and now < nbf - leeway:
        return False, "Token is not yet valid", payload

    # Check issued-at
    iat = payload.get("iat")
    if iat and now < iat - leeway:
        return False, "Token issued in the future", payload

    # Check audience
    aud = payload.get("aud")
    if aud != expected_audience:
        return False, f"Invalid audience: expected '{expected_audience}', got '{aud}'", payload

    # Check issuer
    iss = payload.get("iss")
    if allowed_issuers is not None and iss not in allowed_issuers:
        return False, f"Issuer '{iss}' not in allowed list", payload

    return True, None, payload
