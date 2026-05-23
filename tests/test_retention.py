"""Tests for the retention exception registry."""

import time
import pytest
from src.data.retention import (
    RetentionExceptionRegistry,
    RetentionException,
    MissingOwnerError,
    ExpiredRetentionExceptionError,
    get_registry,
    reset_registry,
)


class TestRetentionExceptionRegistry:
    def setup_method(self):
        self.registry = RetentionExceptionRegistry()
        self.future = time.time() + 86400 * 365  # 1 year from now
        self.review = time.time() + 86400 * 30   # 30 days from now

    def test_add_exception_with_full_metadata(self):
        exc = self.registry.add(
            exception_id="exc-1",
            owner="data-team@example.com",
            reason="Active legal hold -- litigation case #2024-03",
            expiration=self.future,
            review_date=self.review,
        )
        assert exc.id == "exc-1"
        assert exc.owner == "data-team@example.com"
        assert exc.reason == "Active legal hold -- litigation case #2024-03"
        assert not exc.is_expired()

    def test_add_exception_without_owner_raises_error(self):
        with pytest.raises(MissingOwnerError):
            self.registry.add(
                exception_id="exc-bad",
                owner="",
                reason="Missing owner",
                expiration=self.future,
                review_date=self.review,
            )

    def test_add_exception_without_reason_raises_error(self):
        with pytest.raises(ValueError, match="requires a reason"):
            self.registry.add(
                exception_id="exc-bad",
                owner="user@example.com",
                reason="",
                expiration=self.future,
                review_date=self.review,
            )

    def test_add_exception_with_past_expiration_raises_error(self):
        with pytest.raises(ValueError, match="expiration must be in the future"):
            self.registry.add(
                exception_id="exc-exp",
                owner="user@example.com",
                reason="Past expiration",
                expiration=time.time() - 3600,
                review_date=self.review,
            )

    def test_add_exception_with_review_after_expiration_raises_error(self):
        with pytest.raises(ValueError, match="review date"):
            self.registry.add(
                exception_id="exc-review",
                owner="user@example.com",
                reason="Review after expiration",
                expiration=time.time() + 86400 * 10,
                review_date=time.time() + 86400 * 20,  # After expiration
            )

    def test_expired_exception_fails_governance(self):
        self.registry.add(
            exception_id="exc-old",
            owner="user@example.com",
            reason="Will expire soon",
            expiration=self.future,
            review_date=self.review,
        )
        # Simulate check well past expiration
        errors = self.registry.validate_governance(at_time=time.time() + 86400 * 400)
        assert any(isinstance(e, ExpiredRetentionExceptionError) for e in errors)

    def test_clean_governance_returns_empty(self):
        self.registry.add(
            exception_id="exc-good",
            owner="owner@example.com",
            reason="Compliant exception",
            expiration=self.future,
            review_date=self.review,
        )
        errors = self.registry.validate_governance()
        assert len(errors) == 0
        assert self.registry.is_governance_clean() is True

    def test_active_exceptions_grouped_by_owner(self):
        self.registry.add("e1", "alice", "Reason A", self.future, self.review)
        self.registry.add("e2", "alice", "Reason B", self.future, self.review)
        self.registry.add("e3", "bob", "Reason C", self.future, self.review)

        by_owner = self.registry.active_exceptions_by_owner()
        assert len(by_owner["alice"]) == 2
        assert len(by_owner["bob"]) == 1

    def test_expired_exceptions_are_not_in_active_report(self):
        self.registry.add(
            "e-exp", "alice", "Expired one",
            expiration=time.time() - 3600,
            review_date=time.time() - 7200,
        )
        self.registry.add(
            "e-act", "alice", "Active one",
            self.future, self.review,
        )
        by_owner = self.registry.active_exceptions_by_owner()
        assert "alice" in by_owner
        assert len(by_owner["alice"]) == 1
        assert by_owner["alice"][0]["id"] == "e-act"

    def test_remove_exception(self):
        self.registry.add("e1", "owner", "reason", self.future, self.review)
        assert self.registry.get("e1") is not None
        assert self.registry.remove("e1") is True
        assert self.registry.get("e1") is None

    def test_list_all_exceptions(self):
        self.registry.add("e1", "owner1", "reason1", self.future, self.review)
        self.registry.add("e2", "owner2", "reason2", self.future, self.review)
        assert len(self.registry.list_all()) == 2

    def test_expired_exceptions_list(self):
        self.registry.add(
            "e-exp", "owner", "Expired",
            expiration=time.time() - 3600,
            review_date=time.time() - 7200,
        )
        self.registry.add("e-act", "owner", "Active", self.future, self.review)
        expired = self.registry.expired_exceptions()
        assert len(expired) == 1
        assert expired[0].id == "e-exp"

    def test_retention_exception_to_dict(self):
        exc = RetentionException(
            id="exc-1",
            owner="user@example.com",
            reason="Legal hold",
            expiration=self.future,
            review_date=self.review,
        )
        d = exc.to_dict()
        assert d["id"] == "exc-1"
        assert d["owner"] == "user@example.com"
        assert "expired" in d
        assert "review_overdue" in d

    def test_global_registry_singleton(self):
        reset_registry()
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_missing_owner_during_governance_validation(self):
        self.registry.add("e1", "owner", "reason", self.future, self.review)
        exc = self.registry.get("e1")
        object.__setattr__(exc, "owner", "")
        errors = self.registry.validate_governance()
        assert any(isinstance(e, MissingOwnerError) for e in errors)

# 2026-05-23T08:30:00 update
