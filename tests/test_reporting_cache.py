"""Tests for AuthScopeCache."""

import time
from src.common.reporting_cache import AuthContext, AuthScopeCache


def _ctx(user="u1", workspace="ws1", roles=("admin",),
          permissions=("reports:read",), ath=""):
    return AuthContext(
        user_id=user,
        workspace_id=workspace,
        roles=roles,
        permissions=permissions,
        auth_token_hash=ath,
    )


# ------------------------------------------------------------------
# Role downgrade — same user, different roles → no cache reuse
# ------------------------------------------------------------------

def test_role_downgrade_does_not_reuse_cache():
    cache = AuthScopeCache()
    q = {"range": "last_30"}
    admin = _ctx(user="u1", roles=("admin",), permissions=("reports:read_sensitive",))
    viewer = _ctx(user="u1", roles=("viewer",), permissions=("reports:read_public",))

    cache.set("revenue", q, admin, {"rows": [{"amount": 1000}]})
    assert cache.get("revenue", q, viewer) is None


# ------------------------------------------------------------------
# Authorization revalidation failure → evict
# ------------------------------------------------------------------

def test_revalidation_failure_evicts():
    cache = AuthScopeCache()
    q = {"range": "last_7"}
    ctx = _ctx()
    cache.set("pipeline", q, ctx, {"rows": [{"deal": "private"}]})

    # Revalidation returns False → evict
    assert cache.get("pipeline", q, ctx, authorize=lambda _r, _c: False) is None
    # Confirm entry is gone
    assert cache.get("pipeline", q, ctx) is None


# ------------------------------------------------------------------
# Workspace removal → all entries for that workspace invalidated
# ------------------------------------------------------------------

def test_workspace_removal():
    cache = AuthScopeCache()
    q = {"range": "today"}
    ctx = _ctx(workspace="ws-removed")
    cache.set("pipeline", q, ctx, {"rows": [{"deal": "private"}]})

    cache.invalidate_workspace("ws-removed")
    assert cache.get("pipeline", q, ctx) is None


# ------------------------------------------------------------------
# Cross-workspace isolation — same user, different workspace
# ------------------------------------------------------------------

def test_cache_scoped_by_workspace():
    cache = AuthScopeCache()
    q = {"range": "today"}
    ws_a = _ctx(user="u3", workspace="ws-a")
    ws_b = _ctx(user="u3", workspace="ws-b")

    cache.set("usage", q, ws_a, {"ws": "a"})
    assert cache.get("usage", q, ws_b) is None


# ------------------------------------------------------------------
# Cross-user isolation — same workspace, different users
# ------------------------------------------------------------------

def test_cache_scoped_by_user():
    cache = AuthScopeCache()
    q = {"range": "today"}
    user_x = _ctx(user="user-x")
    user_y = _ctx(user="user-y")

    cache.set("report", q, user_x, {"data": "x"})
    assert cache.get("report", q, user_y) is None


# ------------------------------------------------------------------
# Stable cache keys — set/get with different key order
# ------------------------------------------------------------------

def test_stable_cache_keys():
    cache = AuthScopeCache()
    ctx = _ctx()
    cache.set("activity", {"segments": {"paid", "organic"}}, ctx, {"ok": True})
    assert cache.get("activity", {"segments": {"organic", "paid"}}, ctx) == {"ok": True}


# ------------------------------------------------------------------
# TTL expiry — entry expired after wait
# ------------------------------------------------------------------

def test_ttl_expiry():
    cache = AuthScopeCache(default_ttl=0.05)
    ctx = _ctx()
    cache.set("fast", {}, ctx, "value")
    assert cache.get("fast", {}, ctx) == "value"
    time.sleep(0.1)
    assert cache.get("fast", {}, ctx) is None


# ------------------------------------------------------------------
# User invalidation — all entries for a user are removed
# ------------------------------------------------------------------

def test_user_invalidation():
    cache = AuthScopeCache()
    ctx = _ctx(user="u99")
    cache.set("r1", {"a": 1}, ctx, "val1")
    cache.set("r2", {"b": 2}, ctx, "val2")
    cache.invalidate_user("u99")
    assert cache.size == 0


# ------------------------------------------------------------------
# Custom TTL per entry
# ------------------------------------------------------------------

def test_custom_ttl():
    cache = AuthScopeCache(default_ttl=9999)
    ctx = _ctx()
    cache.set("short", {}, ctx, "v", ttl=0.05)
    time.sleep(0.1)
    assert cache.get("short", {}, ctx) is None


# ------------------------------------------------------------------
# Clear all entries
# ------------------------------------------------------------------

def test_clear():
    cache = AuthScopeCache()
    ctx = _ctx()
    cache.set("a", {}, ctx, 1)
    cache.set("b", {}, ctx, 2)
    assert cache.size == 2
    cache.clear()
    assert cache.size == 0


# ------------------------------------------------------------------
# Deep copy independence — mutation by caller doesn't affect cache
# ------------------------------------------------------------------

def test_deep_copy():
    cache = AuthScopeCache()
    ctx = _ctx()
    original = {"items": [1, 2, 3]}
    cache.set("list", {}, ctx, original)
    result = cache.get("list", {}, ctx)
    assert result == original
    result["items"].append(4)  # mutate
    cached_again = cache.get("list", {}, ctx)
    assert cached_again == {"items": [1, 2, 3]}  # unchanged
