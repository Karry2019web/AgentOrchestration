"""Authentication and authorization module.
Separates machine token and user token permissions for automation auth.
"""

import enum
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Set, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------


class TokenType(enum.Enum):
    """Classification of authentication principals."""

    USER = "user"
    """Interactive user session token (browser, CLI login)."""

    MACHINE = "machine"
    """Long-lived machine/automation token (CI/CD, API integrations)."""

    ANONYMOUS = "anonymous"
    """No or unrecognized credentials."""


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------


class Scope(enum.Enum):
    """Fine-grained access scopes for API operations."""

    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_EXECUTE = "agent:execute"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_WRITE = "workflow:write"
    WORKFLOW_EXECUTE = "workflow:execute"
    METRICS_READ = "metrics:read"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    ADMIN = "admin"

    @classmethod
    def from_route(cls, method: str, path: str) -> set:
        """Derive required scopes from an HTTP method + URL path."""
        required = set()

        if "/agents/" in path or "/agents" in path:
            if method in ("GET", "HEAD", "OPTIONS"):
                required.add(cls.AGENT_READ)
            elif method in ("POST", "PUT", "PATCH"):
                if path.endswith("/start") or path.endswith("/stop"):
                    required.add(cls.AGENT_EXECUTE)
                else:
                    required.add(cls.AGENT_WRITE)
            elif method == "DELETE":
                required.add(cls.AGENT_WRITE)

        if "/workflows" in path or "/workflow" in path:
            if method in ("GET", "HEAD"):
                required.add(cls.WORKFLOW_READ)
            elif method in ("POST", "PUT", "PATCH"):
                if path.endswith("/execute") or path.endswith("/dispatch"):
                    required.add(cls.WORKFLOW_EXECUTE)
                else:
                    required.add(cls.WORKFLOW_WRITE)
            elif method == "DELETE":
                required.add(cls.WORKFLOW_WRITE)

        if "/metrics" in path or "/health" in path:
            required.add(cls.METRICS_READ)

        if "/config" in path:
            if method in ("GET", "HEAD"):
                required.add(cls.CONFIG_READ)
            else:
                required.add(cls.CONFIG_WRITE)

        return required

    @classmethod
    def default_for_token_type(cls, token_type):
        """Return the default scope set granted to a principal type."""
        if token_type == TokenType.USER:
            return {
                cls.AGENT_READ, cls.AGENT_WRITE, cls.AGENT_EXECUTE,
                cls.WORKFLOW_READ, cls.WORKFLOW_WRITE, cls.WORKFLOW_EXECUTE,
                cls.METRICS_READ, cls.CONFIG_READ, cls.CONFIG_WRITE,
            }
        if token_type == TokenType.MACHINE:
            return {
                cls.AGENT_READ, cls.AGENT_WRITE, cls.AGENT_EXECUTE,
                cls.WORKFLOW_READ, cls.WORKFLOW_WRITE, cls.WORKFLOW_EXECUTE,
                cls.METRICS_READ, cls.CONFIG_READ,
            }
        return set()


# ---------------------------------------------------------------------------
# Token revocation / staleness
# ---------------------------------------------------------------------------

_revoked_tokens = set()


def revoke_token(token_id):
    """Mark a token as revoked so that subsequent requests fail."""
    _revoked_tokens.add(token_id)


def is_revoked(token_id):
    """Return True if the token has been explicitly revoked."""
    return token_id in _revoked_tokens


# ---------------------------------------------------------------------------
# Token info
# ---------------------------------------------------------------------------


class TokenInfo:
    """Deserialised and validated token information."""

    def __init__(self, token_id, token_type, subject,
                 workspace_role=None, scopes=None,
                 issued_at=0.0, expires_at=None):
        self.token_id = token_id
        self.token_type = token_type
        self.subject = subject
        self.workspace_role = workspace_role
        self.scopes = scopes or set()
        self.issued_at = issued_at
        self.expires_at = expires_at

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def is_stale(self):
        """Stale if expired or explicitly revoked."""
        return self.is_expired or is_revoked(self.token_id)


# ---------------------------------------------------------------------------
# Token validator
# ---------------------------------------------------------------------------


class AuthValidator:
    """Validates bearer tokens and enforces permissions for automation auth.

    Supports two principal types:
    - **user tokens**  — full scope, short-lived, tied to a session.
    - **machine tokens** —  narrower default scope, long-lived, for automation.
    """

    _TOKENS = {
        "mtk_orch_ci_read": TokenInfo(
            token_id="mtk_orch_ci_read",
            token_type=TokenType.MACHINE,
            subject="ci-bot",
            workspace_role="viewer",
            scopes=Scope.default_for_token_type(TokenType.MACHINE),
        ),
        "mtk_orch_deploy": TokenInfo(
            token_id="mtk_orch_deploy",
            token_type=TokenType.MACHINE,
            subject="deploy-bot",
            workspace_role="deployer",
            scopes=Scope.default_for_token_type(TokenType.MACHINE),
        ),
        "utk_orch_admin": TokenInfo(
            token_id="utk_orch_admin",
            token_type=TokenType.USER,
            subject="admin@example.com",
            workspace_role="admin",
            scopes=Scope.default_for_token_type(TokenType.USER) | {Scope.ADMIN},
        ),
        "utk_orch_dev": TokenInfo(
            token_id="utk_orch_dev",
            token_type=TokenType.USER,
            subject="dev@example.com",
            workspace_role="developer",
            scopes=Scope.default_for_token_type(TokenType.USER),
        ),
        "utk_orch_viewer": TokenInfo(
            token_id="utk_orch_viewer",
            token_type=TokenType.USER,
            subject="viewer@example.com",
            workspace_role="viewer",
            scopes={Scope.AGENT_READ, Scope.WORKFLOW_READ, Scope.METRICS_READ},
        ),
    }

    def __init__(self, tokens=None):
        self._tokens = tokens or dict(self._TOKENS)

    def validate(self, raw_token, required_scopes=None):
        """Validate a raw bearer token and return its ``TokenInfo``.

        Raises AuthError if the token is missing, revoked, expired,
        stale, or lacks the required scopes.
        """
        token_id = self._extract_token_id(raw_token)
        info = self._tokens.get(token_id)

        if info is None:
            if not token_id:
                raise AuthError("Missing or empty token", status_code=401)
            raise AuthError("Unknown token: " + token_id[:20] + "...", status_code=401)

        if is_revoked(info.token_id):
            raise AuthError("Token has been revoked", status_code=401)

        if info.is_expired:
            raise AuthError("Token has expired", status_code=401)

        if info.is_stale:
            raise AuthError("Token is stale", status_code=401)

        if required_scopes and not required_scopes.issubset(info.scopes):
            missing = required_scopes - info.scopes
            scope_str = ", ".join(s.value for s in sorted(missing, key=lambda x: x.value))
            raise AuthError(
                "Insufficient permissions. Missing scope(s): " + scope_str,
                status_code=403,
            )

        return info

    def classify_token(self, raw_token):
        """Determine the type of a token without full validation."""
        token_id = self._extract_token_id(raw_token)
        if not token_id:
            return TokenType.ANONYMOUS
        info = self._tokens.get(token_id)
        if info is None:
            return TokenType.ANONYMOUS
        return info.token_type

    @staticmethod
    def _extract_token_id(raw_token):
        """Strip the ``Bearer `` prefix and return the opaque token string."""
        if raw_token.startswith("Bearer "):
            return raw_token[7:].strip()
        return raw_token.strip()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Raised when authentication or authorization fails."""

    def __init__(self, message, status_code=401):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
