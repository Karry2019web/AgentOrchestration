"""Tests for the auth module - machine vs user token permissions."""

import time
import pytest

from src.common.auth import (
    AuthValidator,
    AuthError,
    TokenType,
    TokenInfo,
    Scope,
    revoke_token,
    is_revoked,
)


class TestTokenTypes:
    """Verify machine and user tokens are classified correctly."""

    def test_machine_token_classification(self):
        validator = AuthValidator()
        assert validator.classify_token("Bearer mtk_orch_ci_read") == TokenType.MACHINE
        assert validator.classify_token("Bearer mtk_orch_deploy") == TokenType.MACHINE

    def test_user_token_classification(self):
        validator = AuthValidator()
        assert validator.classify_token("Bearer utk_orch_admin") == TokenType.USER
        assert validator.classify_token("Bearer utk_orch_dev") == TokenType.USER

    def test_anonymous_token_classification(self):
        validator = AuthValidator()
        assert validator.classify_token("") == TokenType.ANONYMOUS
        assert validator.classify_token("Bearer invalid_token_xxx") == TokenType.ANONYMOUS
        assert validator.classify_token("garbage") == TokenType.ANONYMOUS

    def test_missing_bearer_prefix(self):
        validator = AuthValidator()
        assert validator.classify_token("mtk_orch_ci_read") == TokenType.MACHINE


class TestTokenValidation:
    """Verify validation logic - expiration, revocation, scopes."""

    def test_valid_machine_token(self):
        validator = AuthValidator()
        info = validator.validate("Bearer mtk_orch_ci_read")
        assert info.token_type == TokenType.MACHINE
        assert info.subject == "ci-bot"

    def test_valid_user_token(self):
        validator = AuthValidator()
        info = validator.validate("Bearer utk_orch_dev")
        assert info.token_type == TokenType.USER
        assert info.subject == "dev@example.com"

    def test_expired_token_is_rejected(self):
        expired = TokenInfo(
            token_id="expired_001",
            token_type=TokenType.MACHINE,
            subject="expired-bot",
            scopes=Scope.default_for_token_type(TokenType.MACHINE),
            expires_at=time.time() - 1,
        )
        validator = AuthValidator(tokens={"expired_001": expired})
        with pytest.raises(AuthError) as exc:
            validator.validate("Bearer expired_001")
        assert exc.value.status_code == 401
        assert "expired" in exc.value.message.lower()

    def test_revoked_token_is_rejected(self):
        revoke_token("mtk_orch_ci_read")
        validator = AuthValidator()
        with pytest.raises(AuthError) as exc:
            validator.validate("Bearer mtk_orch_ci_read")
        assert exc.value.status_code == 401
        assert "revoked" in exc.value.message.lower()

    def test_unknown_token_is_rejected(self):
        validator = AuthValidator()
        with pytest.raises(AuthError) as exc:
            validator.validate("Bearer idonotexist_999")
        assert exc.value.status_code == 401

    def test_empty_token_is_rejected(self):
        validator = AuthValidator()
        with pytest.raises(AuthError) as exc:
            validator.validate("")
        assert exc.value.status_code == 401


class TestScopeAuthorization:
    """Verify scope-based access control for different token types."""

    def test_machine_token_default_scopes(self):
        info = AuthValidator().validate("Bearer mtk_orch_deploy")
        assert Scope.AGENT_READ in info.scopes
        assert Scope.AGENT_WRITE in info.scopes
        assert Scope.WORKFLOW_EXECUTE in info.scopes
        assert Scope.CONFIG_WRITE not in info.scopes

    def test_machine_token_denied_config_write(self):
        validator = AuthValidator()
        with pytest.raises(AuthError) as exc:
            validator.validate("Bearer mtk_orch_deploy", required_scopes={Scope.CONFIG_WRITE})
        assert exc.value.status_code == 403
        assert "Insufficient" in exc.value.message

    def test_user_token_has_config_write(self):
        info = AuthValidator().validate("Bearer utk_orch_dev")
        assert Scope.CONFIG_WRITE in info.scopes

    def test_user_token_with_admin_scope(self):
        info = AuthValidator().validate("Bearer utk_orch_admin")
        assert Scope.ADMIN in info.scopes

    def test_viewer_token_denied_agent_write(self):
        with pytest.raises(AuthError) as exc:
            AuthValidator().validate(
                "Bearer utk_orch_viewer",
                required_scopes={Scope.AGENT_WRITE},
            )
        assert exc.value.status_code == 403


class TestScopeFromRoute:
    """Verify Scope.from_route maps HTTP methods + paths correctly."""

    def test_get_agents_requires_read(self):
        scopes = Scope.from_route("GET", "/api/v2/agents")
        assert Scope.AGENT_READ in scopes
        assert Scope.AGENT_WRITE not in scopes

    def test_post_agents_requires_write(self):
        scopes = Scope.from_route("POST", "/api/v2/agents")
        assert Scope.AGENT_WRITE in scopes
        assert Scope.AGENT_READ not in scopes

    def test_post_agent_start_requires_execute(self):
        scopes = Scope.from_route("POST", "/api/v2/agents/abc123/start")
        assert Scope.AGENT_EXECUTE in scopes
        assert Scope.AGENT_WRITE not in scopes

    def test_delete_agent_requires_write(self):
        scopes = Scope.from_route("DELETE", "/api/v2/agents/abc123")
        assert Scope.AGENT_WRITE in scopes

    def test_health_check_metrics(self):
        scopes = Scope.from_route("GET", "/health")
        assert Scope.METRICS_READ in scopes

    def test_config_get_is_read(self):
        scopes = Scope.from_route("GET", "/api/v2/config")
        assert Scope.CONFIG_READ in scopes

    def test_config_post_is_write(self):
        scopes = Scope.from_route("POST", "/api/v2/config")
        assert Scope.CONFIG_WRITE in scopes


class TestRevocation:
    """Verify the in-memory revocation set works correctly."""

    def test_revoke_and_check(self):
        test_id = "test_revoke_001"
        assert not is_revoked(test_id)
        revoke_token(test_id)
        assert is_revoked(test_id)

    def test_revoked_token_fails_validation(self):
        validator = AuthValidator()
        test_token = TokenInfo(
            token_id="temp_token_xyz",
            token_type=TokenType.USER,
            subject="temp@test.com",
            scopes=Scope.default_for_token_type(TokenType.USER),
        )
        validator._tokens["temp_token_xyz"] = test_token

        assert validator.validate("Bearer temp_token_xyz") is not None
        revoke_token("temp_token_xyz")
        with pytest.raises(AuthError) as exc:
            validator.validate("Bearer temp_token_xyz")
        assert "revoked" in exc.value.message.lower()
