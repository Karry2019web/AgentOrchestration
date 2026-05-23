"""Tests for governance — retention exception registry."""

import time
import pytest
from src.common.governance import (
    RetentionException,
    RetentionExceptionRegistry,
    GovernanceValidationError,
)


class TestRetentionException:
    def test_is_expired_when_past_expiration(self):
        exc = RetentionException(
            dataset_id="ds-1",
            owner="alice",
            reason="Migration in progress",
            expiration=1000,
            review_date=900,
            created_at=800,
        )
        assert exc.is_expired(now=2000) is True

    def test_is_not_expired_before_expiration(self):
        exc = RetentionException(
            dataset_id="ds-1",
            owner="alice",
            reason="Migration in progress",
            expiration=2000,
            review_date=1500,
        )
        assert exc.is_expired(now=1000) is False

    def test_is_review_overdue(self):
        exc = RetentionException(
            dataset_id="ds-1",
            owner="alice",
            reason="Migration in progress",
            expiration=2000,
            review_date=1000,
        )
        assert exc.is_review_overdue(now=1500) is True

    def test_is_not_review_overdue_before_review_date(self):
        exc = RetentionException(
            dataset_id="ds-1",
            owner="alice",
            reason="Migration in progress",
            expiration=2000,
            review_date=1500,
        )
        assert exc.is_review_overdue(now=1000) is False


class TestRetentionExceptionRegistry:
    def setup_method(self):
        self.registry = RetentionExceptionRegistry()
        self.now = 1_000_000
        self.future = self.now + 86_400 * 90  # 90 days from now
        self.review = self.now + 86_400 * 30  # 30 days from now

    def test_register_requires_owner(self):
        with pytest.raises(GovernanceValidationError) as excinfo:
            self.registry.register("ds-1", "", "Some reason", self.future, self.review)
        assert "owner" in str(excinfo.value).lower()

    def test_register_requires_reason(self):
        with pytest.raises(GovernanceValidationError) as excinfo:
            self.registry.register("ds-1", "bob", "", self.future, self.review)
        assert "reason" in str(excinfo.value).lower()

    def test_register_requires_expiration(self):
        with pytest.raises(GovernanceValidationError) as excinfo:
            self.registry.register("ds-1", "bob", "Some reason", 0, self.review)
        assert "expiration" in str(excinfo.value).lower()

    def test_register_requires_review_date(self):
        with pytest.raises(GovernanceValidationError) as excinfo:
            self.registry.register("ds-1", "bob", "Some reason", self.future, 0)
        assert "review date" in str(excinfo.value).lower()

    def test_register_validates_review_before_expiration(self):
        with pytest.raises(GovernanceValidationError) as excinfo:
            self.registry.register(
                "ds-1", "bob", "Some reason", self.future, self.future + 1
            )
        assert "after expiration" in str(excinfo.value).lower()

    def test_successful_registration(self):
        exc = self.registry.register(
            "ds-1", "alice", "Migration in progress", self.future, self.review
        )
        assert exc.owner == "alice"
        assert exc.dataset_id == "ds-1"
        assert exc.reason == "Migration in progress"
        assert exc.expiration == self.future

    def test_get_by_id(self):
        exc = self.registry.register(
            "ds-1", "alice", "Migration", self.future, self.review
        )
        fetched = self.registry.get(exc.exception_id)
        assert fetched is not None
        assert fetched.owner == "alice"

    def test_get_by_dataset(self):
        self.registry.register(
            "ds-1", "alice", "Migration", self.future, self.review
        )
        fetched = self.registry.get_by_dataset("ds-1")
        assert fetched is not None
        assert fetched.owner == "alice"

    def test_remove(self):
        exc = self.registry.register(
            "ds-1", "alice", "Migration", self.future, self.review
        )
        assert self.registry.remove(exc.exception_id) is True
        assert self.registry.get(exc.exception_id) is None

    def test_remove_nonexistent(self):
        assert self.registry.remove("nonexistent") is False

    def test_validate_governance_with_expired_exception(self):
        past = self.now - 1
        self.registry.register(
            "ds-1", "alice", "Migration", past, self.review
        )
        failures = self.registry.validate_governance(now=self.now)
        assert len(failures) == 1
        assert "expired" in failures[0].lower()

    def test_validate_governance_with_overdue_review(self):
        overdue_review = self.now - 1
        self.registry.register(
            "ds-1", "alice", "Migration", self.future, overdue_review
        )
        failures = self.registry.validate_governance(now=self.now)
        assert len(failures) == 1
        assert "overdue" in failures[0].lower() or "review" in failures[0].lower()

    def test_validate_governance_all_clean(self):
        self.registry.register(
            "ds-1", "alice", "Migration", self.future, self.review
        )
        failures = self.registry.validate_governance(now=self.now)
        assert len(failures) == 0

    def test_report_by_owner(self):
        self.registry.register(
            "ds-1", "alice", "Migration 1", self.future, self.review
        )
        self.registry.register(
            "ds-2", "alice", "Migration 2", self.future, self.review
        )
        self.registry.register(
            "ds-3", "bob", "Legacy data", self.future, self.review
        )
        report = self.registry.report_by_owner()
        assert len(report["alice"]) == 2
        assert len(report["bob"]) == 1

    def test_report_by_owner_excludes_expired(self):
        past = self.now - 1
        self.registry.register(
            "ds-1", "alice", "Active", self.future, self.review
        )
        self.registry.register(
            "ds-2", "bob", "Expired", past, self.review
        )
        report = self.registry.report_by_owner()
        assert "alice" in report
        assert "bob" not in report or len(report.get("bob", [])) == 0

    def test_active_count(self):
        past = self.now - 1
        self.registry.register(
            "ds-1", "alice", "Active", self.future, self.review
        )
        self.registry.register(
            "ds-2", "bob", "Expired", past, self.review
        )
        assert self.registry.active_count() == 1

# 2026-05-23T10:04:00 update
