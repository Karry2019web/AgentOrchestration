"""Tests for analytics lineage tracking."""

import pytest
from datetime import datetime, timezone

from src.analytics.lineage import (
    LineageMetadata,
    LineageValidator,
    LineageValidationError,
    trace_metric,
    publish_dataset,
)


class TestLineageMetadata:
    def test_create_basic(self):
        meta = LineageMetadata(
            source_table="raw.task_records",
            transform_version="1.0.0",
        )
        assert meta.source_table == "raw.task_records"
        assert meta.transform_version == "1.0.0"
        assert meta.source_columns == []
        assert meta.notes is None

    def test_create_with_all_fields(self):
        meta = LineageMetadata(
            source_table="raw.task_records",
            transform_version="2.1.0",
            source_columns=["task_id", "duration", "status"],
            transform_id="tfn-001",
            notes="Daily aggregation batch",
        )
        assert meta.source_columns == ["task_id", "duration", "status"]
        assert meta.transform_id == "tfn-001"

    def test_to_dict(self):
        meta = LineageMetadata(
            source_table="raw.tasks",
            transform_version="1.0.0",
            source_columns=["id"],
        )
        d = meta.to_dict()
        assert d["source_table"] == "raw.tasks"
        assert d["transform_version"] == "1.0.0"
        assert "generated_at" in d

    def test_to_json(self):
        meta = LineageMetadata(
            source_table="raw.events",
            transform_version="1.0.0",
        )
        j = meta.to_json()
        assert "raw.events" in j
        assert "transform_version" in j

    def test_from_dict(self):
        data = {
            "source_table": "raw.task_records",
            "transform_version": "1.5.0",
            "source_columns": ["a", "b"],
        }
        meta = LineageMetadata.from_dict(data)
        assert meta.source_table == "raw.task_records"
        assert meta.transform_version == "1.5.0"
        assert meta.source_columns == ["a", "b"]

    def test_frozen_immutable(self):
        meta = LineageMetadata(source_table="t", transform_version="1")
        with pytest.raises(AttributeError):
            meta.source_table = "other"


class TestLineageValidator:
    def setup_method(self):
        self.validator = LineageValidator()

    def test_valid_lineage_in_root(self):
        dataset = {
            "source_table": "raw.task_records",
            "transform_version": "1.0.0",
            "generated_at": "2026-01-01T00:00:00Z",
            "data": {"avg_duration": 42.5},
        }
        meta = self.validator.validate(dataset)
        assert isinstance(meta, LineageMetadata)
        assert meta.source_table == "raw.task_records"

    def test_valid_lineage_in_lineage_key(self):
        dataset = {
            "_lineage": {
                "source_table": "raw.task_records",
                "transform_version": "1.0.0",
                "generated_at": "2026-01-01T00:00:00Z",
            },
            "data": {"avg_duration": 42.5},
        }
        meta = self.validator.validate(dataset)
        assert meta.source_table == "raw.task_records"

    def test_missing_source_table(self):
        with pytest.raises(LineageValidationError) as exc:
            self.validator.validate({"transform_version": "1.0.0", "generated_at": "now"})
        assert "source_table" in str(exc.value)

    def test_missing_transform_version(self):
        with pytest.raises(LineageValidationError) as exc:
            self.validator.validate({"source_table": "raw.tasks", "generated_at": "now"})
        assert "transform_version" in str(exc.value)

    def test_missing_generated_at(self):
        with pytest.raises(LineageValidationError) as exc:
            self.validator.validate({"source_table": "raw.tasks", "transform_version": "1.0"})
        assert "generated_at" in str(exc.value)

    def test_missing_all_fields(self):
        with pytest.raises(LineageValidationError) as exc:
            self.validator.validate({})
        for f in ["source_table", "transform_version", "generated_at"]:
            assert f in str(exc.value)

    def test_empty_source_table(self):
        with pytest.raises(LineageValidationError):
            self.validator.validate({
                "source_table": "",
                "transform_version": "1.0.0",
                "generated_at": "now",
            })

    def test_validate_or_skip_valid(self):
        assert self.validator.validate_or_skip({
            "source_table": "raw.tasks",
            "transform_version": "1.0",
            "generated_at": "now",
        }) is True

    def test_validate_or_skip_invalid(self):
        assert self.validator.validate_or_skip({}) is False

    def test_lineage_in_lineage_key_missing_fields(self):
        dataset = {
            "_lineage": {"source_table": "raw.tasks"},
            "data": {},
        }
        with pytest.raises(LineageValidationError):
            self.validator.validate(dataset)


class TestTraceMetric:
    def test_trace_basic(self):
        meta = LineageMetadata(
            source_table="raw.task_records",
            transform_version="2.1.0",
            source_columns=["task_id", "duration"],
        )
        trace = trace_metric("avg_duration", meta)
        assert "avg_duration" in trace
        assert "raw.task_records" in trace
        assert "2.1.0" in trace
        assert "task_id" in trace
        assert "duration" in trace

    def test_trace_no_columns(self):
        meta = LineageMetadata(
            source_table="raw.events",
            transform_version="1.0.0",
        )
        trace = trace_metric("event_count", meta)
        assert "event_count" in trace
        assert "raw.events" in trace


class TestPublishDataset:
    def test_publish_with_lineage(self):
        result = publish_dataset(
            {"metric": "avg_duration"},
            lineage=LineageMetadata(source_table="raw.tasks", transform_version="1.0"),
        )
        assert "_lineage" in result
        assert result["_lineage"]["source_table"] == "raw.tasks"
        assert result["metric"] == "avg_duration"

    def test_publish_without_lineage_embedded(self):
        dataset = {
            "_lineage": {
                "source_table": "raw.tasks",
                "transform_version": "1.0",
                "generated_at": "2026-01-01T00:00:00Z",
            },
            "metric": "avg_duration",
        }
        result = publish_dataset(dataset)
        assert result["_lineage"]["source_table"] == "raw.tasks"

    def test_publish_missing_lineage(self):
        with pytest.raises(LineageValidationError):
            publish_dataset({"metric": "avg_duration"})

# 2026-05-23T20:00:00 update
