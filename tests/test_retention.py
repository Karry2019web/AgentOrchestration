"""Tests for the retention exception registry."""

import time
import pytest
from src.common.retention import RetentionExceptionRegistry


class TestRetentionExceptionRegistry:
    def setup_method(self):
        self.registry = RetentionExceptionRegistry()
        self.future = time.time() + 86400 * 30  # 30 days
        self.review = time.time() + 86400 * 7   # 7 days

    def test_add_exception(self):
        self.registry.add_exception("ds-1", "alice@corp.com",
                                    "Legal hold for audit", self.future, self.review)
        exc = self.registry.get_exception("ds-1")
        assert exc is not None
        assert exc["owner"] == "alice@corp.com"
        assert exc["reason"] == "Legal hold for audit"

    def test_add_exception_missing_owner_raises(self):
        with pytest.raises(ValueError, match="Owner is required"):
            self.registry.add_exception("ds-2", "", "Reason", self.future, self.review)

    def test_add_exception_missing_reason_raises(self):
        with pytest.raises(ValueError, match="Reason is required"):
            self.registry.add_exception("ds-3", "bob", "", self.future, self.review)

    def test_add_exception_past_expiration_raises(self):
        with pytest.raises(ValueError, match="Expiration date must be in the future"):
            self.registry.add_exception("ds-4", "bob", "Reason",
                                        time.time() - 3600, self.review)

    def test_validate_governance_valid(self):
        self.registry.add_exception("ds-5", "carol@corp.com",
                                    "Compliance", self.future, self.review)
        result = self.registry.validate_governance("ds-5")
        assert result["valid"] is True

    def test_validate_governance_no_exception(self):
        result = self.registry.validate_governance("ds-none")
        assert result["valid"] is True

    def test_list_active_by_owner(self):
        self.registry.add_exception("ds-a", "alice", "Reason A", self.future, self.review)
        self.registry.add_exception("ds-b", "alice", "Reason B", self.future, self.review)
        self.registry.add_exception("ds-c", "bob", "Reason C", self.future, self.review)
        alice_exceptions = self.registry.list_active_by_owner("alice")
        assert len(alice_exceptions) == 2

    def test_remove_exception(self):
        self.registry.add_exception("ds-6", "dave", "Reason", self.future, self.review)
        assert self.registry.remove_exception("ds-6") is True
        assert self.registry.remove_exception("nonexistent") is False
