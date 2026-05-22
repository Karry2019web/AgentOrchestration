"""Tests for handler version compatibility and registry."""

import pytest
from src.agent.handler_version import (
    HandlerVersionRegistry,
    HandlerVersionError,
    SemVer,
    VersionComparison,
)


class TestSemVer:
    """Tests for semantic version parsing and comparison."""

    def test_parse_full(self):
        v = SemVer.parse("2.1.3")
        assert v.major == 2
        assert v.minor == 1
        assert v.patch == 3

    def test_parse_with_pre_release(self):
        v = SemVer.parse("1.0.0-alpha")
        assert v.major == 1
        assert v.pre_release == "alpha"

    def test_parse_with_build(self):
        v = SemVer.parse("1.0.0+build.123")
        assert v.major == 1
        assert v.build == "build.123"

    def test_parse_empty(self):
        v = SemVer.parse("")
        assert v.major == 0

    def test_parse_invalid_fallback(self):
        v = SemVer.parse("not.a.version")
        assert v.major == 0
        assert v.minor == 0
        assert v.patch == 0

    def test_is_compatible_same_version(self):
        v1 = SemVer.parse("1.2.3")
        v2 = SemVer.parse("1.2.3")
        compatible, comp = v1.is_compatible_with(v2)
        assert compatible is True
        assert comp == VersionComparison.EXACT

    def test_is_compatible_minor_bump(self):
        v1 = SemVer.parse("1.2.0")
        v2 = SemVer.parse("1.3.0")
        compatible, comp = v1.is_compatible_with(v2)
        assert compatible is True
        assert comp == VersionComparison.MINOR

    def test_is_compatible_patch_bump(self):
        v1 = SemVer.parse("1.2.0")
        v2 = SemVer.parse("1.2.1")
        compatible, comp = v1.is_compatible_with(v2)
        assert compatible is True
        assert comp == VersionComparison.PATCH

    def test_is_incompatible_major_bump(self):
        v1 = SemVer.parse("1.0.0")
        v2 = SemVer.parse("2.0.0")
        compatible, comp = v1.is_compatible_with(v2)
        assert compatible is False
        assert comp == VersionComparison.MAJOR

    def test_is_compatible_with_minor_disabled(self):
        v1 = SemVer.parse("1.2.0")
        v2 = SemVer.parse("1.3.0")
        compatible, comp = v1.is_compatible_with(v2, allow_minor=False)
        assert compatible is False
        assert comp == VersionComparison.MINOR

    def test_str_representation(self):
        v = SemVer.parse("3.2.1-beta+001")
        assert str(v) == "3.2.1-beta+001"

    def test_semver_equality(self):
        assert SemVer.parse("1.0.0") == SemVer.parse("1.0.0")
        assert SemVer.parse("1.0.0") != SemVer.parse("1.0.1")


class TestHandlerVersionRegistry:
    """Tests for the handler version registry."""

    def setup_method(self):
        self.registry = HandlerVersionRegistry()

    def test_register_handler(self):
        handler_id = self.registry.register("data-processor", "1.0.0", "worker")
        assert handler_id == "data-processor@1.0.0"

    def test_register_creates_version_entry(self):
        self.registry.register("dp", "1.0.0", "worker")
        versions = self.registry.get_versions("dp")
        assert "1.0.0" in versions

    def test_register_multiple_versions(self):
        self.registry.register("dp", "1.0.0", "worker")
        self.registry.register("dp", "1.1.0", "worker")
        versions = self.registry.get_versions("dp")
        assert len(versions) == 2
        assert "1.0.0" in versions
        assert "1.1.0" in versions

    def test_register_invalid_version_raises_error(self):
        with pytest.raises(HandlerVersionError):
            self.registry.register("bad", "0.0.0", "worker")

    def test_resolve_latest(self):
        self.registry.register("svc", "1.0.0", "service")
        self.registry.register("svc", "1.5.0", "service")
        self.registry.register("svc", "2.0.0", "service")

        handler = self.registry.get_handler("svc")
        assert handler is not None
        assert str(handler.version) == "2.0.0"

    def test_resolve_by_version(self):
        self.registry.register("svc", "1.0.0", "service")
        self.registry.register("svc", "1.5.0", "service")

        handler = self.registry.get_handler("svc", version_constraint="1.0.0")
        assert handler is not None
        assert str(handler.version) == "1.0.0"

    def test_resolve_nonexistent_handler(self):
        handler = self.registry.get_handler("nonexistent")
        assert handler is None

    def test_validate_safe_major_upgrade_with_explicit_compat(self):
        self.registry.register("svc", "1.0.0", "service")
        self.registry.register("svc", "2.0.0", "service",
                              compatible_versions=["1.0.0"])

        is_safe, reason = self.registry.validate_upgrade("svc", "1.0.0", "2.0.0")
        assert is_safe is True
        assert "explicitly allowed" in reason

    def test_validate_unsafe_major_upgrade(self):
        self.registry.register("svc", "1.0.0", "service")
        self.registry.register("svc", "2.0.0", "service")

        is_safe, reason = self.registry.validate_upgrade("svc", "1.0.0", "2.0.0")
        assert is_safe is False
        assert "Breaking changes" in reason

    def test_cache_invalidation_on_new_registration(self):
        self.registry.register("svc", "1.0.0", "service")
        h1 = self.registry.get_handler("svc")
        assert str(h1.version) == "1.0.0"

        # Register a new version — cache should be invalidated
        self.registry.register("svc", "2.0.0", "service")
        h2 = self.registry.get_handler("svc")
        assert str(h2.version) == "2.0.0"

    def test_remove_handler(self):
        self.registry.register("svc", "1.0.0", "service")
        assert len(self.registry.list_handlers("svc")) == 1
        assert self.registry.remove_handler("svc@1.0.0") is True
        assert len(self.registry.list_handlers("svc")) == 0

    def test_remove_nonexistent_handler(self):
        assert self.registry.remove_handler("nonexistent") is False

    def test_list_all_handlers(self):
        self.registry.register("a", "1.0.0", "type-a")
        self.registry.register("b", "1.0.0", "type-b")
        all_handlers = self.registry.list_handlers()
        assert len(all_handlers) == 2

    def test_list_handlers_filtered_by_name(self):
        self.registry.register("a", "1.0.0", "type-a")
        self.registry.register("b", "1.0.0", "type-b")
        only_a = self.registry.list_handlers("a")
        assert len(only_a) == 1
        assert only_a[0].name == "a"

    def test_invalidate_handler(self):
        self.registry.register("svc", "1.0.0", "service")
        self.registry.get_handler("svc")  # populate cache
        self.registry.invalidate_handler("svc")
        # Cache miss should re-resolve — nothing to assert explicitly
        # but verifies no crash
        assert self.registry.get_handler("svc") is not None
