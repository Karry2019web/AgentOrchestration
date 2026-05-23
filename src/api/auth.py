"""Token service — JWT validation with audience enforcement for service-to-service calls."""

import time
import os
import logging
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

# In-memory set of revoked token jti values.
# In production this should be backed by Redis with TTL matching token expiry.
_revoked_tokens: Set[str] = set()

# Expected audience for agent-worker service-to-service calls.
AGENT_WORKER_AUDIENCE = "agent-worker-api"

# Expected audience for browser-based sessions.
BROWSER_AUDIENCE = "browser-ui"


class TokenValidationError(Exception):
    """Raised when a token fails validation."""


class TokenService:
    """Validates JWT tokens and enforces audience for service-to-service calls."""

    def __init__(self):
        # In production the secret key or JWKS endpoint would be injected.
        # For this implementation we derive a local secret from the environment.
        self._secret = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")

    def _decode_token(self, token: str) -> Optional[Dict]:
        """Decode and validate a JWT token.

        Uses PyJWT if available, otherwise returns a mock for development.
        """
        try:
            import jwt as pyjwt
            payload = pyjwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                options={"require": ["exp", "iat", "aud", "sub", "jti"]},
            )
            return payload
        except ImportError:
            logger.warning("PyJWT not installed — falling back to dev-mode validation")
            return self._dev_decode(token)
        except Exception as exc:
            raise TokenValidationError(f"Token validation failed: {exc}") from exc

    def _dev_decode(self, token: str) -> Dict:
        """Development-only token parsing. Not cryptographically secure."""
        import base64
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise TokenValidationError("Malformed token")
            # Pad for base64 decoding
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return payload
        except (ValueError, IndexError, json.JSONDecodeError) as exc:
            raise TokenValidationError(f"Dev token decode failed: {exc}") from exc

    def validate_audience(self, payload: Dict, expected_audience: str) -> None:
        """Verify the token audience matches the expected value."""
        aud = payload.get("aud")
        if not aud:
            raise TokenValidationError("Token missing 'aud' claim")
        if isinstance(aud, list):
            if expected_audience not in aud:
                raise TokenValidationError(
                    f"Token audience {aud} does not include expected '{expected_audience}'"
                )
        elif aud != expected_audience:
            raise TokenValidationError(
                f"Token audience '{aud}' does not match expected '{expected_audience}'"
            )

    def is_revoked(self, jti: str) -> bool:
        """Check if a token has been revoked."""
        return jti in _revoked_tokens

    def revoke(self, jti: str) -> None:
        """Revoke a token by its JWT ID."""
        _revoked_tokens.add(jti)

    def validate_service_token(self, token: str) -> Dict:
        """Full validation for a service-to-service token.

        Returns the validated token payload on success.
        Raises TokenValidationError on failure.
        """
        payload = self._decode_token(token)

        # Check expiry
        now = time.time()
        exp = payload.get("exp", 0)
        if now > exp:
            raise TokenValidationError("Token has expired")

        # Check issued-at (reject future tokens)
        iat = payload.get("iat", 0)
        if iat > now + 5:
            raise TokenValidationError("Token issued in the future")

        # Check revocation
        jti = payload.get("jti", "")
        if jti and self.is_revoked(jti):
            raise TokenValidationError("Token has been revoked")

        # Enforce audience for service-to-service calls
        self.validate_audience(payload, AGENT_WORKER_AUDIENCE)

        return payload

    def validate_browser_token(self, token: str) -> Dict:
        """Validate a browser session token.

        Returns the validated token payload on success.
        """
        payload = self._decode_token(token)

        now = time.time()
        exp = payload.get("exp", 0)
        if now > exp:
            raise TokenValidationError("Token has expired")

        iat = payload.get("iat", 0)
        if iat > now + 5:
            raise TokenValidationError("Token issued in the future")

        jti = payload.get("jti", "")
        if jti and self.is_revoked(jti):
            raise TokenValidationError("Token has been revoked")

        self.validate_audience(payload, BROWSER_AUDIENCE)

        return payload


# Singleton instance
token_service = TokenService()
