"""Authentication and authorization service for operator tokens.

Implements least-privilege scope enforcement for run cancellation
and other protected orchestration actions.
"""

import json
import time
import hmac
import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class TokenScope(str, Enum):
    """Granular scope definitions for operator tokens."""
    RUN_READ = "run:read"
    RUN_CANCEL = "run:cancel"
    RUN_CREATE = "run:create"
    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_DELETE = "agent:delete"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_WRITE = "workflow:write"
    METRICS_READ = "metrics:read"
    ADMIN = "admin"


_RUN_CANCELLATION_MIN_SCOPES: Set[str] = {TokenScope.RUN_CANCEL.value, TokenScope.ADMIN.value}


class TokenValidationResult(Enum):
    VALID = "valid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    MALFORMED = "malformed"
    ANONYMOUS = "anonymous"
    WRONG_WORKSPACE = "wrong_workspace"


@dataclass
class TokenPayload:
    subject: str
    workspace_id: str
    scopes: List[str]
    issued_at: float
    expires_at: float
    token_id: str
    role: str = "operator"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return now > self.expires_at

    def has_scope(self, required_scope: str) -> bool:
        return required_scope in self.scopes or TokenScope.ADMIN.value in self.scopes


class SessionStore:
    def __init__(self):
        self._revoked_tokens: Dict[str, float] = {}
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

    def revoke(self, token_id: str) -> None:
        self._revoked_tokens[token_id] = time.time()

    def is_revoked(self, token_id: str) -> bool:
        return token_id in self._revoked_tokens

    def register_session(self, token_id: str, session_data: Dict[str, Any]) -> None:
        self._active_sessions[token_id] = session_data

    def get_session(self, token_id: str) -> Optional[Dict[str, Any]]:
        return self._active_sessions.get(token_id)

    def remove_session(self, token_id: str) -> None:
        self._active_sessions.pop(token_id, None)
        self.revoke(token_id)


class OperatorTokenService:
    def __init__(
        self,
        signing_key: Optional[str] = None,
        session_store: Optional[SessionStore] = None,
        default_ttl: int = 3600,
    ):
        self._signing_key = signing_key or self._generate_default_key()
        self._session_store = session_store or SessionStore()
        self._default_ttl = default_ttl

    @staticmethod
    def _generate_default_key() -> str:
        return hashlib.sha256(b"operator-token-service-dev-key").hexdigest()

    def _sign(self, payload: Dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            self._signing_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def create_token(
        self,
        subject: str,
        workspace_id: str,
        scopes: List[str],
        role: str = "operator",
        ttl: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        token_id = hashlib.sha256(
            f"{subject}:{workspace_id}:{time.time_ns()}".encode()
        ).hexdigest()[:16]
        now = time.time()
        payload = {
            "sub": subject,
            "ws": workspace_id,
            "scp": scopes,
            "iat": now,
            "exp": now + (ttl or self._default_ttl),
            "jti": token_id,
            "role": role,
            "meta": metadata or {},
        }
        signature = self._sign(payload)
        self._session_store.register_session(
            token_id,
            {
                "subject": subject,
                "workspace_id": workspace_id,
                "scopes": scopes,
                "role": role,
                "issued_at": now,
                "expires_at": payload["exp"],
            },
        )
        return self._encode_token(payload, signature)

    def _encode_token(self, payload: Dict[str, Any], signature: str) -> str:
        import base64
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        sig_b64 = base64.urlsafe_b64encode(signature.encode()).rstrip(b"=").decode()
        return f"{payload_b64}.{sig_b64}"

    def decode_token(self, token: str) -> Dict[str, Any]:
        import base64
        parts = token.split(".")
        if len(parts) != 2:
            raise ValueError("Malformed token format")
        payload_b64 = parts[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        return json.loads(base64.urlsafe_b64decode(payload_b64))

    def validate_token(
        self, token: str, required_scopes: Optional[Set[str]] = None
    ) -> TokenValidationResult:
        try:
            payload = self.decode_token(token)
        except (ValueError, json.JSONDecodeError, Exception):
            return TokenValidationResult.MALFORMED
        parts = token.split(".")
        expected_sig = self._sign(payload)
        actual_sig_b64 = parts[1]
        import base64
        try:
            padding = 4 - len(actual_sig_b64) % 4
            if padding != 4:
                actual_sig_decoded = base64.urlsafe_b64decode(actual_sig_b64 + "=" * padding).decode()
            else:
                actual_sig_decoded = base64.urlsafe_b64decode(actual_sig_b64).decode()
        except Exception:
            return TokenValidationResult.MALFORMED
        if not hmac.compare_digest(expected_sig, actual_sig_decoded):
            return TokenValidationResult.MALFORMED
        token_id = payload.get("jti", "")
        now = time.time()
        exp = payload.get("exp", 0)
        if now > exp:
            return TokenValidationResult.EXPIRED
        if token_id and self._session_store.is_revoked(token_id):
            return TokenValidationResult.REVOKED
        if required_scopes:
            token_scopes = set(payload.get("scp", []))
            # Admin wildcard: admin token satisfies any scope requirement
            if TokenScope.ADMIN.value not in token_scopes:
                if not required_scopes.intersection(token_scopes):
                    return TokenValidationResult.INSUFFICIENT_SCOPE
        return TokenValidationResult.VALID

    def get_token_payload(self, token: str) -> Optional[TokenPayload]:
        validation = self.validate_token(token)
        if validation != TokenValidationResult.VALID:
            return None
        try:
            payload = self.decode_token(token)
            return TokenPayload(
                subject=payload.get("sub", ""),
                workspace_id=payload.get("ws", ""),
                scopes=payload.get("scp", []),
                issued_at=payload.get("iat", 0),
                expires_at=payload.get("exp", 0),
                token_id=payload.get("jti", ""),
                role=payload.get("role", "operator"),
                metadata=payload.get("meta", {}),
            )
        except Exception:
            return None

    def revoke_token(self, token_id: str) -> None:
        self._session_store.revoke(token_id)

    def validate_run_cancellation(self, token: str, agent_workspace: str) -> TokenValidationResult:
        validation = self.validate_token(token, required_scopes=_RUN_CANCELLATION_MIN_SCOPES)
        if validation != TokenValidationResult.VALID:
            return validation
        try:
            payload = self.decode_token(token)
            token_workspace = payload.get("ws", "")
            if token_workspace != agent_workspace:
                return TokenValidationResult.WRONG_WORKSPACE
        except Exception:
            return TokenValidationResult.MALFORMED
        return TokenValidationResult.VALID

    def validate_token_for_workspace(self, token: str, workspace_id: str) -> TokenValidationResult:
        validation = self.validate_token(token)
        if validation != TokenValidationResult.VALID:
            return validation
        try:
            payload = self.decode_token(token)
            if payload.get("ws", "") != workspace_id:
                return TokenValidationResult.WRONG_WORKSPACE
        except Exception:
            return TokenValidationResult.MALFORMED
        return TokenValidationResult.VALID


_default_service = None


def get_operator_token_service() -> OperatorTokenService:
    global _default_service
    if _default_service is None:
        _default_service = OperatorTokenService()
    return _default_service


def get_session_store() -> SessionStore:
    return get_operator_token_service()._session_store
