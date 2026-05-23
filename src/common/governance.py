"""Governance — Retention exception registry with data owner tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from uuid import uuid4


@dataclass
class RetentionException:
    """A retention exception with full accountability metadata.

    Attributes:
        exception_id: Unique identifier for this exception.
        dataset_id: The dataset or artifact category the exception applies to.
        owner: The accountable data owner (person or team).
        reason: Human-readable explanation for the exception.
        expiration: Unix timestamp when the exception expires.
        review_date: Unix timestamp when the exception must be reviewed.
        created_at: Unix timestamp when the exception was created.
    """

    exception_id: str = field(default_factory=lambda: str(uuid4()))
    dataset_id: str = ""
    owner: str = ""
    reason: str = ""
    expiration: float = 0.0
    review_date: float = 0.0
    created_at: float = field(default_factory=time.time)

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Check if the exception has expired."""
        if now is None:
            now = time.time()
        return self.expiration > 0 and now > self.expiration

    def is_review_overdue(self, now: Optional[float] = None) -> bool:
        """Check if the exception is past its scheduled review date."""
        if now is None:
            now = time.time()
        return self.review_date > 0 and now > self.review_date


class GovernanceValidationError(Exception):
    """Raised when a governance validation check fails."""

    def __init__(self, message: str):
        super().__init__(f"Governance validation error: {message}")


class RetentionExceptionRegistry:
    """Registry of retention exceptions with owner metadata enforcement."""

    def __init__(self):
        self._exceptions: Dict[str, RetentionException] = {}
        self._dataset_exceptions: Dict[str, str] = {}  # dataset_id -> exception_id

    def register(
        self,
        dataset_id: str,
        owner: str,
        reason: str,
        expiration: float,
        review_date: float,
    ) -> RetentionException:
        """Register a new retention exception with required owner metadata.

        Args:
            dataset_id: The dataset or artifact category.
            owner: Accountable data owner (person or team).
            reason: Human-readable explanation for the exception.
            expiration: Unix timestamp when the exception expires.
            review_date: Unix timestamp for the next review.

        Returns:
            The newly created RetentionException.

        Raises:
            GovernanceValidationError: If owner, reason, expiration, or
                review_date is missing or invalid.
        """
        # Validate required fields
        if not owner or not owner.strip():
            raise GovernanceValidationError(
                "Retention exception must have an accountable owner. "
                f"Got empty owner for dataset '{dataset_id}'."
            )
        if not reason or not reason.strip():
            raise GovernanceValidationError(
                "Retention exception must have a reason. "
                f"Got empty reason for dataset '{dataset_id}'."
            )
        if expiration <= 0:
            raise GovernanceValidationError(
                f"Retention exception for dataset '{dataset_id}' must have "
                f"a valid expiration timestamp (got {expiration})."
            )
        if review_date <= 0:
            raise GovernanceValidationError(
                f"Retention exception for dataset '{dataset_id}' must have "
                f"a valid review date timestamp (got {review_date})."
            )
        if review_date > expiration:
            raise GovernanceValidationError(
                f"Retention exception for dataset '{dataset_id}' has a review date "
                f"({review_date}) after expiration ({expiration}). "
                "Review date must be on or before expiration."
            )

        exception = RetentionException(
            dataset_id=dataset_id,
            owner=owner.strip(),
            reason=reason.strip(),
            expiration=expiration,
            review_date=review_date,
        )
        self._exceptions[exception.exception_id] = exception
        self._dataset_exceptions[dataset_id] = exception.exception_id
        return exception

    def get(self, exception_id: str) -> Optional[RetentionException]:
        """Look up an exception by its ID."""
        return self._exceptions.get(exception_id)

    def get_by_dataset(self, dataset_id: str) -> Optional[RetentionException]:
        """Look up an exception by dataset ID."""
        exception_id = self._dataset_exceptions.get(dataset_id)
        if exception_id:
            return self._exceptions.get(exception_id)
        return None

    def remove(self, exception_id: str) -> bool:
        """Remove an exception by its ID."""
        exception = self._exceptions.pop(exception_id, None)
        if exception:
            self._dataset_exceptions.pop(exception.dataset_id, None)
            return True
        return False

    def validate_governance(self, now: Optional[float] = None) -> List[str]:
        """Run governance validation across all exceptions.

        Checks:
        - Expired exceptions are flagged.
        - Review-overdue exceptions are flagged.

        Returns:
            A list of validation failure messages (empty = all passing).
        """
        if now is None:
            now = time.time()

        failures: List[str] = []
        for exc in self._exceptions.values():
            if exc.is_expired(now):
                failures.append(
                    f"Exception {exc.exception_id} for dataset "
                    f"'{exc.dataset_id}' (owner: {exc.owner}) has expired "
                    f"at {exc.expiration}."
                )
            if exc.is_review_overdue(now):
                failures.append(
                    f"Exception {exc.exception_id} for dataset "
                    f"'{exc.dataset_id}' (owner: {exc.owner}) is past its "
                    f"scheduled review date {exc.review_date}."
                )
        return failures

    def report_by_owner(self) -> Dict[str, List[RetentionException]]:
        """Group active (non-expired) exceptions by owner.

        Returns:
            A dictionary mapping owner names to lists of their active
            retention exceptions.
        """
        now = time.time()
        groups: Dict[str, List[RetentionException]] = {}
        for exc in self._exceptions.values():
            if not exc.is_expired(now):
                groups.setdefault(exc.owner, []).append(exc)
        return groups

    def active_count(self) -> int:
        """Return the number of non-expired exceptions."""
        now = time.time()
        return sum(1 for e in self._exceptions.values() if not e.is_expired(now))

    def __len__(self) -> int:
        return len(self._exceptions)

# 2026-05-23T10:04:00 update
