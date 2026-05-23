"""Tests for export filter validation and job creation."""

import pytest
from datetime import date
from src.data.export import (
    ExportFilterValidator,
    ExportJob,
    ExportValidationError,
    ExportFilter,
)


class TestExportFilterValidator:
    def test_valid_full_filters(self):
        """All valid filters pass validation."""
        result = ExportFilterValidator.validate_and_normalize(
            date_from="2025-01-01",
            date_to="2025-12-31",
            workspace="prod-east",
            status="completed",
        )
        assert result.date_from == date(2025, 1, 1)
        assert result.date_to == date(2025, 12, 31)
        assert result.workspace == "prod-east"
        assert result.status == "completed"

    def test_optional_filters_can_be_none(self):
        """All filters are optional — None is accepted."""
        result = ExportFilterValidator.validate_and_normalize()
        assert result.date_from is None
        assert result.date_to is None
        assert result.workspace is None
        assert result.status is None

    def test_partial_filters_accepted(self):
        """Only date_from works without other filters."""
        result = ExportFilterValidator.validate_and_normalize(date_from="2025-06-01")
        assert result.date_from == date(2025, 6, 1)
        assert result.date_to is None

    def test_status_is_case_insensitive_and_normalized(self):
        """Status is normalized to lowercase."""
        result = ExportFilterValidator.validate_and_normalize(status="COMPLETED")
        assert result.status == "completed"

        result = ExportFilterValidator.validate_and_normalize(status="Pending")
        assert result.status == "pending"

    @pytest.mark.parametrize("bad_date", ["not-a-date", "2025/01/01", "01-01-2025", "", "2025-13-01"])
    def test_invalid_date_from_rejected(self, bad_date):
        """Invalid date_from values are rejected."""
        with pytest.raises(ExportValidationError, match="Invalid date_from"):
            ExportFilterValidator.validate_and_normalize(date_from=bad_date)

    @pytest.mark.parametrize("bad_date", ["not-a-date", "2025/12/31", ""])
    def test_invalid_date_to_rejected(self, bad_date):
        """Invalid date_to values are rejected."""
        with pytest.raises(ExportValidationError, match="Invalid date_to"):
            ExportFilterValidator.validate_and_normalize(date_to=bad_date)

    def test_empty_date_range_rejected(self):
        """date_from after date_to produces an empty range error."""
        with pytest.raises(ExportValidationError, match="Empty date range"):
            ExportFilterValidator.validate_and_normalize(
                date_from="2025-12-31",
                date_to="2025-01-01",
            )

    def test_boundary_same_date_accepted(self):
        """date_from equal to date_to is a valid single-day range."""
        result = ExportFilterValidator.validate_and_normalize(
            date_from="2025-06-15",
            date_to="2025-06-15",
        )
        assert result.date_from == result.date_to == date(2025, 6, 15)

    def test_empty_workspace_rejected(self):
        """Empty workspace string is rejected."""
        with pytest.raises(ExportValidationError, match="workspace filter cannot be empty"):
            ExportFilterValidator.validate_and_normalize(workspace="")

    def test_unsupported_status_rejected(self):
        """Status not in the valid set is rejected."""
        with pytest.raises(ExportValidationError, match="Unsupported status"):
            ExportFilterValidator.validate_and_normalize(status="archived")

    @pytest.mark.parametrize("valid_status", ["pending", "running", "completed", "failed", "cancelled"])
    def test_all_valid_statuses_accepted(self, valid_status):
        """Every status in the valid set is accepted."""
        result = ExportFilterValidator.validate_and_normalize(status=valid_status)
        assert result.status == valid_status


class TestExportJob:
    def test_create_with_valid_filters(self):
        """ExportJob.create produces a ready-to-enqueue job."""
        job = ExportJob.create({
            "date_from": "2025-01-01",
            "date_to": "2025-03-31",
            "status": "completed",
        })
        assert job.job_id is not None
        assert job.filter.date_from == date(2025, 1, 1)
        assert job.filter.date_to == date(2025, 3, 31)

    def test_create_rejects_invalid_filters(self):
        """ExportJob.create propagates validation errors."""
        with pytest.raises(ExportValidationError):
            ExportJob.create({"status": "archived"})

    def test_to_dict_serialization(self):
        """to_dict produces a JSON-safe representation."""
        job = ExportJob.create({
            "date_from": "2025-06-01",
            "workspace": "prod-east",
            "status": "running",
        })
        d = job.to_dict()
        assert d["id"] == job.job_id
        assert d["filter"]["date_from"] == "2025-06-01"
        assert d["filter"]["workspace"] == "prod-east"
        assert d["filter"]["status"] == "running"
        assert "created_at" in d
