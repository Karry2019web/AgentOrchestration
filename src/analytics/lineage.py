"""Lineage Tracking — Machine-readable metadata for transformed datasets.

Provides structured lineage metadata that records source table, transform version,
and generation time for every transformed analytics dataset. Includes validation
that rejects publish attempts with missing lineage, and helper functions for
tracing a reporting metric back to its source data.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LineageMetadata:
    """Immutable lineage metadata attached to every transformed dataset.

    Attributes:
        source_table: Name of the source table or raw data source.
        transform_version: Semver string identifying the transform version.
        generated_at: ISO-8601 timestamp of when the transform ran.
        source_columns: Optional list of source column names consumed.
        transform_id: Optional unique identifier for the transform run.
        notes: Optional human-readable notes about the transform.
    """

    source_table: str
    transform_version: str
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_columns: List[str] = field(default_factory=list)
    transform_id: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LineageMetadata":
        return cls(
            source_table=data["source_table"],
            transform_version=data["transform_version"],
            generated_at=data.get("generated_at", datetime.now(timezone.utc).isoformat()),
            source_columns=data.get("source_columns", []),
            transform_id=data.get("transform_id"),
            notes=data.get("notes"),
        )


class LineageValidationError(Exception):
    """Raised when a dataset is missing required lineage metadata."""


class LineageValidator:
    """Validates that transformed datasets carry complete lineage metadata before publish.

    Usage:
        validator = LineageValidator()
        validator.validate(dataset)          # raises LineageValidationError on failure
        validator.validate_or_skip(dataset)  # returns False on failure without raising
    """

    REQUIRED_FIELDS = ["source_table", "transform_version", "generated_at"]

    def validate(self, dataset: Dict[str, Any]) -> LineageMetadata:
        """Validate that *dataset* carries complete lineage metadata.

        *dataset* may carry lineage in a ``"_lineage"`` key, or the root dict
        itself may be the lineage metadata.

        Returns the validated ``LineageMetadata`` on success.

        Raises:
            LineageValidationError: if any required field is missing or empty.
        """
        lineage_data = dataset.get("_lineage", dataset)

        missing = []
        for field_name in self.REQUIRED_FIELDS:
            value = lineage_data.get(field_name)
            if not value:
                missing.append(field_name)

        if missing:
            raise LineageValidationError(
                f"Dataset is missing required lineage field(s): {', '.join(missing)}. "
                f"Provide a '_lineage' key with at least: source_table, "
                f"transform_version, generated_at."
            )

        return LineageMetadata.from_dict(lineage_data)

    def validate_or_skip(self, dataset: Dict[str, Any]) -> bool:
        """Validate lineage without raising -- returns ``True`` if valid."""
        try:
            self.validate(dataset)
            return True
        except LineageValidationError:
            return False


def trace_metric(metric_name: str, lineage: LineageMetadata) -> str:
    """Return a human-readable trace string explaining how *metric_name*
    maps back to its source data through *lineage*.

    Example::

        >>> meta = LineageMetadata(
        ...     source_table="raw.task_records",
        ...     transform_version="2.1.0",
        ...     source_columns=["task_id", "duration", "status"],
        ... )
        >>> print(trace_metric("avg_duration_by_status", meta))
        Metric 'avg_duration_by_status' is derived from table 'raw.task_records'
        via transform v2.1.0 (columns: task_id, duration, status).
        Generated at: 2026-05-23T20:00:00+00:00
    """
    parts = [
        f"Metric '{metric_name}' is derived from table '{lineage.source_table}'",
        f"via transform v{lineage.transform_version}",
    ]
    if lineage.source_columns:
        parts[-1] += f" (columns: {', '.join(lineage.source_columns)})"
    parts.append(f".")
    parts.append(f"Generated at: {lineage.generated_at}")
    return " ".join(parts)


def publish_dataset(dataset: Dict[str, Any], lineage: Optional[LineageMetadata] = None) -> Dict[str, Any]:
    """Publish a transformed dataset, attaching lineage metadata.

    If *lineage* is provided it is embedded in the dataset under ``"_lineage"``.
    If *lineage* is ``None`` the dataset''s existing ``"_lineage"`` is validated.

    Returns the dataset dict enriched with lineage metadata.

    Raises:
        LineageValidationError: if no lineage can be resolved.
    """
    if lineage is not None:
        dataset = {**dataset, "_lineage": lineage.to_dict()}
    LineageValidator().validate(dataset)
    return dataset

# 2026-05-23T20:00:00 update
