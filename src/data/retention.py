"""Retention Exception Registry — Governance metadata for data retention exceptions.

Every retention exception must have an accountable owner, reason, expiration date,
and review date. Expired exceptions fail governance validation.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class RetentionExceptionError(Exception):
    """Base exception for retention exception errors."""
    pass


class ExpiredRetentionExceptionError(RetentionExceptionError):
    """Raised when a retention exception has expired."""
    def __init__(self, exception_id: str, owner: str, expired_at: str):
        super().__init__(
            f"Retention exception {exception_id} for owner '{owner}' "
            f"expired at {expired_at}. "
            "Renew or remove the exception before proceeding."
        )


class MissingOwnerError(RetentionExceptionError):
    """Raised when a retention exception is missing owner metadata."""
    def __init__(self, exception_id: str):
        super().__init__(
            f"Retention exception {exception_id} is missing owner metadata. "
            "Every exception requires owner, reason, expiration, and review date."
        )


@dataclass
class RetentionException:
    """A retention exception with full governance metadata.

    Attributes:
        id: Unique identifier for this exception.
        owner: Accountable data owner (email, team, or username).
        reason: Justification for the retention exception.
        expiration: Unix timestamp when the exception expires.
        review_date: Unix timestamp by which the exception must be reviewed.
        created_at: Unix timestamp when the exception was created.
        dataset: Optional dataset or artifact category this applies to.
    """
    id: str
    owner: str
    reason: str
    expiration: float
    review_date: float
    created_at: float = field(default_factory=time.time)
    dataset: Optional[str] = None

    def is_expired(self, at_time: Optional[float] = None) -> bool:
        """Check whether this exception has expired."""
        check_time = at_time if at_time is not None else time.time()
        return check_time >= self.expiration

    def is_review_overdue(self, at_time: Optional[float] = None) -> bool:
        """Check whether the review date has passed."""
        check_time = at_time if at_time is not None else time.time()
        return check_time >= self.review_date

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "id": self.id,
            "owner": self.owner,
            "reason": self.reason,
            "expiration": self.expiration,
            "review_date": self.review_date,
            "created_at": self.created_at,
            "dataset": self.dataset,
            "expired": self.is_expired(),
            "review_overdue": self.is_review_overdue(),
        }


class RetentionExceptionRegistry:
    """Registry for managing retention exceptions with governance validation.

    All exceptions require owner, reason, expiration, and review date.
    Expired exceptions are reported and block governance validation.
    """

    def __init__(self):
        self._exceptions: Dict[str, RetentionException] = {}

    def add(
        self,
        exception_id: str,
        owner: str,
        reason: str,
        expiration: float,
        review_date: float,
        dataset: Optional[str] = None,
    ) -> RetentionException:
        """Register a new retention exception with full owner metadata.

        Args:
            exception_id: Unique identifier for the exception.
            owner: Accountable data owner (email, team, or username).
            reason: Justification for the exception.
            expiration: Unix timestamp when the exception expires.
            review_date: Unix timestamp by which review is required.
            dataset: Optional dataset this exception applies to.

        Returns:
            The newly created RetentionException.

        Raises:
            MissingOwnerError: If owner is empty or None.
            ValueError: If expiration or review_date are invalid.
        """
        if not owner or not owner.strip():
            raise MissingOwnerError(exception_id)
        if not reason or not reason.strip():
            raise ValueError(f"Retention exception {exception_id} requires a reason.")
        if expiration <= time.time():
            raise ValueError(
                f"Retention exception {exception_id} expiration must be in the future."
            )
        if review_date <= time.time():
            raise ValueError(
                f"Retention exception {exception_id} review date must be in the future."
            )
        if review_date > expiration:
            raise ValueError(
                f"Retention exception {exception_id} review date ({review_date}) "
                f"must be on or before expiration ({expiration})."
            )

        exception = RetentionException(
            id=exception_id,
            owner=owner.strip(),
            reason=reason.strip(),
            expiration=expiration,
            review_date=review_date,
            dataset=dataset,
        )
        self._exceptions[exception_id] = exception
        return exception

    def get(self, exception_id: str) -> Optional[RetentionException]:
        """Retrieve a retention exception by ID."""
        return self._exceptions.get(exception_id)

    def remove(self, exception_id: str) -> bool:
        """Remove a retention exception by ID. Returns True if removed."""
        return self._exceptions.pop(exception_id, None) is not None

    def list_all(self) -> List[RetentionException]:
        """Return all registered retention exceptions."""
        return list(self._exceptions.values())

    def validate_governance(self, at_time: Optional[float] = None) -> List[RetentionExceptionError]:
        """Validate all exceptions for governance compliance.

        Checks:
        - Every exception has owner metadata.
        - No expired exceptions.

        Returns a list of errors. An empty list means governance passes.
        """
        errors: List[RetentionExceptionError] = []
        check_time = at_time if at_time is not None else time.time()

        for exc in self._exceptions.values():
            if not exc.owner or not exc.owner.strip():
                errors.append(MissingOwnerError(exc.id))
            if exc.is_expired(check_time):
                errors.append(ExpiredRetentionExceptionError(
                    exc.id, exc.owner,
                    datetime.fromtimestamp(exc.expiration, tz=timezone.utc).isoformat()
                ))

        return errors

    def is_governance_clean(self, at_time: Optional[float] = None) -> bool:
        """Quick check: are all exceptions governance-compliant?"""
        return len(self.validate_governance(at_time)) == 0

    def active_exceptions_by_owner(
        self, at_time: Optional[float] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group active (non-expired) exceptions by owner for reporting.

        Returns a dict mapping owner -> list of exception dicts.
        """
        check_time = at_time if at_time is not None else time.time()
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for exc in self._exceptions.values():
            if not exc.is_expired(check_time):
                groups.setdefault(exc.owner, []).append(exc.to_dict())
        return groups

    def expired_exceptions(
        self, at_time: Optional[float] = None
    ) -> List[RetentionException]:
        """Return all expired exceptions."""
        check_time = at_time if at_time is not None else time.time()
        return [exc for exc in self._exceptions.values() if exc.is_expired(check_time)]


# Module-level singleton for shared use
_default_registry: Optional[RetentionExceptionRegistry] = None


def get_registry() -> RetentionExceptionRegistry:
    """Get or create the default retention exception registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = RetentionExceptionRegistry()
    return _default_registry


def reset_registry() -> None:
    """Reset the default registry (useful for testing)."""
    global _default_registry
    _default_registry = None

# 2026-05-23T08:30:00 update
