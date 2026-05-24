import pytest
from src.common.metrics import (
    MetricsCollector,
    apply_export_metadata,
    validate_schema_version,
    UnsupportedSchemaVersion,
    SCHEMA_VERSION,
    FIELD_DICTIONARY,
)


class TestSchemaVersionedExports:
    def test_export_includes_schema_version(self):
        wrapped = apply_export_metadata({"test": "value"})
        assert "schema_version" in wrapped
        assert wrapped["schema_version"] == SCHEMA_VERSION

    def test_export_includes_generated_at(self):
        wrapped = apply_export_metadata({})
        assert "generated_at" in wrapped
        assert len(wrapped["generated_at"]) > 0

    def test_export_includes_field_dictionary(self):
        wrapped = apply_export_metadata({})
        assert "field_dictionary" in wrapped
        assert isinstance(wrapped["field_dictionary"], dict)
        assert "schema_version" in wrapped["field_dictionary"]

    def test_export_preserves_data(self):
        orig = {"counters": {"req": 5}, "gauges": {"temp": 30.0}}
        wrapped = apply_export_metadata(orig)
        assert wrapped["data"] == orig

    def test_validate_schema_version_passes(self):
        export = {"schema_version": "1.0.0"}
        assert validate_schema_version(export) is True

    def test_validate_missing_schema_version_raises(self):
        with pytest.raises(UnsupportedSchemaVersion, match="Missing schema_version"):
            validate_schema_version({})

    def test_validate_unsupported_version_raises(self):
        export = {"schema_version": "2.0.0"}
        with pytest.raises(UnsupportedSchemaVersion, match="Unsupported schema version"):
            validate_schema_version(export)

    def test_metrics_snapshot_includes_metadata(self):
        collector = MetricsCollector()
        collector.increment("test.counter")
        snap = collector.snapshot()
        assert "schema_version" in snap
        assert "generated_at" in snap
        assert "field_dictionary" in snap
        assert "data" in snap
        assert snap["data"]["counters"]["test.counter"] == 1

    def test_validate_empty_export_raises(self):
        with pytest.raises(UnsupportedSchemaVersion):
            validate_schema_version({})

    def test_field_dictionary_completeness(self):
        required_keys = {"schema_version", "generated_at", "field_dictionary",
                         "counters", "gauges", "histograms"}
        assert required_keys <= set(FIELD_DICTIONARY.keys())

    def test_export_rejects_invalid_consumer(self):
        """Simulate a downstream consumer rejecting an unsupported version."""
        export = apply_export_metadata({"msg": "hello"})
        # Mutate to an unknown version to simulate version drift
        export["schema_version"] = "99.0.0"
        with pytest.raises(UnsupportedSchemaVersion):
            validate_schema_version(export)

    def test_metrics_snapshot_rejects_missing_metadata(self):
        """Ensure snapshot always has metadata by checking raw fields."""
        collector = MetricsCollector()
        snap = collector.snapshot()
        # If metadata were stripped, the schema_version key would be absent
        assert "schema_version" in snap
        # A consumer that strips metadata before processing SHOULD fail validation
        stripped = {"data": snap.get("data", {})}
        with pytest.raises(UnsupportedSchemaVersion):
            validate_schema_version(stripped)
