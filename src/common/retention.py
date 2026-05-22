"""Retention exception registry — data governance for retention exceptions."""

import time
from datetime import datetime
from typing import Dict, List, Optional
from threading import Lock


class RetentionException:
    def __init__(self, dataset_id: str, owner: str, reason: str,
                 expiration_date: float, review_date: float):
        self.dataset_id = dataset_id
        self.owner = owner
        self.reason = reason
        self.expiration_date = expiration_date
        self.review_date = review_date
        self.created_at = time.time()

    def is_expired(self) -> bool:
        return time.time() > self.expiration_date

    def needs_review(self) -> bool:
        return time.time() > self.review_date


class RetentionExceptionRegistry:
    """Manages retention exceptions with owner, reason, expiration, and review tracking."""

    def __init__(self):
        self._lock = Lock()
        self._exceptions: Dict[str, RetentionException] = {}

    def add_exception(self, dataset_id: str, owner: str, reason: str,
                      expiration_date: float, review_date: float) -> None:
        if not owner or not owner.strip():
            raise ValueError("Owner is required for retention exceptions")
        if not reason or not reason.strip():
            raise ValueError("Reason is required for retention exceptions")
        if expiration_date <= time.time():
            raise ValueError("Expiration date must be in the future")
        if review_date <= time.time():
            raise ValueError("Review date must be in the future")
        if review_date > expiration_date:
            raise ValueError("Review date must be before or equal to expiration date")

        with self._lock:
            self._exceptions[dataset_id] = RetentionException(
                dataset_id=dataset_id,
                owner=owner.strip(),
                reason=reason.strip(),
                expiration_date=expiration_date,
                review_date=review_date,
            )

    def get_exception(self, dataset_id: str) -> Optional[Dict]:
        with self._lock:
            exc = self._exceptions.get(dataset_id)
            if not exc:
                return None
            return self._to_dict(exc)

    def remove_exception(self, dataset_id: str) -> bool:
        with self._lock:
            if dataset_id in self._exceptions:
                del self._exceptions[dataset_id]
                return True
            return False

    def validate_governance(self, dataset_id: str) -> Dict:
        """Validate that a dataset's retention exception is compliant."""
        with self._lock:
            exc = self._exceptions.get(dataset_id)
            if not exc:
                return {"valid": True, "reason": "No retention exception on record"}
            result = self._to_dict(exc)
            issues = []
            if exc.is_expired():
                issues.append("expired")
            if not exc.owner or not exc.owner.strip():
                issues.append("missing_owner")
            if exc.needs_review():
                issues.append("needs_review")
            result["valid"] = len(issues) == 0
            result["governance_issues"] = issues
            return result

    def list_active_by_owner(self, owner: str) -> List[Dict]:
        """Group active exceptions by owner."""
        with self._lock:
            return [
                self._to_dict(exc)
                for exc in self._exceptions.values()
                if exc.owner == owner and not exc.is_expired()
            ]

    def list_expired(self) -> List[Dict]:
        with self._lock:
            return [
                self._to_dict(exc)
                for exc in self._exceptions.values()
                if exc.is_expired()
            ]

    def list_all(self) -> List[Dict]:
        with self._lock:
            return [self._to_dict(exc) for exc in self._exceptions.values()]

    def _to_dict(self, exc: RetentionException) -> Dict:
        return {
            "dataset_id": exc.dataset_id,
            "owner": exc.owner,
            "reason": exc.reason,
            "expiration_date": exc.expiration_date,
            "review_date": exc.review_date,
            "created_at": exc.created_at,
            "is_expired": exc.is_expired(),
            "needs_review": exc.needs_review(),
        }


retention_registry = RetentionExceptionRegistry()
