"""Tests for authorization service — project role enforcement on environment variable reads."""

import time
import pytest
from src.common.permissions import AuthorizationService, ProjectRole


def test_authorized_developer_can_read_env_vars():
    svc = AuthorizationService()
    svc.register_token("dev-key-123", "project-alpha")
    svc.set_role("user:dev-key-", "project-alpha", "developer", ttl=3600)
    assert svc.check_environment_read_access("dev-key-123") is True


def test_viewer_cannot_read_env_vars():
    svc = AuthorizationService()
    svc.register_token("view-key-456", "project-beta")
    svc.set_role("user:view-key-", "project-beta", "viewer", ttl=3600)
    assert svc.check_environment_read_access("view-key-456") is False


def test_anonymous_token_rejected():
    svc = AuthorizationService()
    assert svc.check_environment_read_access("unknown-token") is False


def test_expired_role_rejected():
    svc = AuthorizationService()
    svc.register_token("exp-key-789", "project-gamma")
    svc.set_role("user:exp-key-", "project-gamma", "developer", ttl=-1)  # already expired
    assert svc.check_environment_read_access("exp-key-789") is False


def test_stale_credentials_invalidated():
    svc = AuthorizationService()
    svc.register_token("stale-key-999", "project-delta")
    svc.set_role("user:stale-key-", "project-delta", "developer", ttl=-1)
    svc.invalidate_role("user:stale-key-", "project-delta")
    assert svc.check_environment_read_access("stale-key-999") is False


def test_token_without_role_is_rejected():
    svc = AuthorizationService()
    svc.register_token("no-role-key", "project-epsilon")
    # No set_role call
    assert svc.check_environment_read_access("no-role-key") is False


def test_admin_can_read_env_vars():
    svc = AuthorizationService()
    svc.register_token("admin-key-001", "project-zeta")
    svc.set_role("user:admin-key-", "project-zeta", "admin", ttl=3600)
    assert svc.check_environment_read_access("admin-key-001") is True


def test_role_hierarchy_levels():
    assert ProjectRole("p", "viewer", "u").level == 0
    assert ProjectRole("p", "developer", "u").level == 1
    assert ProjectRole("p", "admin", "u").level == 2
    assert ProjectRole("p", "owner", "u").level == 3
    assert ProjectRole("p", "unknown", "u").level == -1


def test_enforce_environment_read_raises_for_viewer():
    svc = AuthorizationService()
    svc.register_token("view-key", "project-iota")
    svc.set_role("user:view-key-", "project-iota", "viewer", ttl=3600)
    with pytest.raises(PermissionError):
        svc.enforce_environment_read("view-key")


def test_enforce_environment_read_passes_for_developer():
    svc = AuthorizationService()
    svc.register_token("dev-key", "project-kappa")
    svc.set_role("user:dev-key-", "project-kappa", "developer", ttl=3600)
    # Should not raise
    svc.enforce_environment_read("dev-key")
