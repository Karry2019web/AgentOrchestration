"""Export filter validation and normalized job storage.

Validates date ranges, workspace filters, and status filters before
enqueuing bulk download jobs. Rejects invalid filters synchronously
so workers never receive malformed export requests.
"""

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Dict, List, Optional, Set
from uuid import uuid4


VALID_EXPORT_STATUSES: Set[str] = {"pending", "running", "completed", "failed", "cancelled"}


class ExportValidationError(ValueError):
    """Raised when export filter values fail validation."""


@dataclass
class ExportFilter:
    """Validated and normalized export filter values."""

    date_from: Optional[date] = None
    date_to: Optional[date] = None
    workspace: Optional[str] = None
    status: Optional[str] = None

    def to_dict(self) -> Dict:
        result: Dict = {}
        if self.date_from is not None:
            result["date_from"] = self.date_from.isoformat()
        if self.date_to is not None:
            result["date_to"] = self.date_to.isoformat()
        if self.workspace is not None:
            result["workspace"] = self.workspace
        if self.status is not None:
            result["status"] = self.status
        return result


class ExportFilterValidator:
    """Synchronous validator and normalizer for export filters.

    Used as a gate before enqueuing an export job so that invalid
    filters are rejected at the API layer, not discovered hours later
    inside a worker.
    """

    VALID_STATUSES = VALID_EXPORT_STATUSES

    @classmethod
    def validate_and_normalize(
        cls,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        workspace: Optional[str] = None,
        status: Optional[str] = None,
    ) -> ExportFilter:
        """Validate and normalize raw filter values into an ExportFilter.

        Raises ExportValidationError on any invalid input.
        """
        parsed_from: Optional[date] = None
        parsed_to: Optional[date] = None

        # --- date_from ---
        if date_from is not None:
            try:
                parsed_from = date.fromisoformat(date_from)
            except (ValueError, TypeError):
                raise ExportValidationError(
                    f"Invalid date_from '{date_from}': expected ISO date format (YYYY-MM-DD)"
                )

        # --- date_to ---
        if date_to is not None:
            try:
                parsed_to = date.fromisoformat(date_to)
            except (ValueError, TypeError):
                raise ExportValidationError(
                    f"Invalid date_to '{date_to}': expected ISO date format (YYYY-MM-DD)"
                )

        # --- range coherence ---
        if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
            raise ExportValidationError(
                f"Empty date range: date_from ({parsed_from}) is after date_to ({parsed_to})"
            )

        # --- workspace ---
        if workspace is not None and not workspace.strip():
            raise ExportValidationError("workspace filter cannot be empty")

        # --- status ---
        if status is not None:
            normalized_status = status.strip().lower()
            if normalized_status not in cls.VALID_STATUSES:
                raise ExportValidationError(
                    f"Unsupported status '{status}'. Valid statuses: {', '.join(sorted(cls.VALID_STATUSES))}"
                )
            status = normalized_status

        return ExportFilter(
            date_from=parsed_from,
            date_to=parsed_to,
            workspace=workspace.strip() if workspace else None,
            status=status,
        )


@dataclass
class ExportJob:
    """A validated export job ready for enqueueing."""

    job_id: str = field(default_factory=lambda: str(uuid4()))
    filter: ExportFilter = field(default_factory=ExportFilter)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            "id": self.job_id,
            "filter": self.filter.to_dict(),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def create(cls, filter_values: Dict) -> "ExportJob":
        """Validate filters and create a ready-to-enqueue ExportJob."""
        validated = ExportFilterValidator.validate_and_normalize(**filter_values)
        return cls(filter=validated)
