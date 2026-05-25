"""Tests for data lake ingestion pipeline with purpose enforcement."""

from src.common.data_lake import (
    DataClass,
    DestinationPolicy,
    DestinationPolicyRecord,
    PurposeManifest,
    DataClassificationRegistry,
    IngestionPipeline,
    DataLakeWrite,
    DestinationNotFoundError,
    DataClassNotAllowedError,
)


class TestDataClassificationRegistry:
    def test_default_registrations(self):
        registry = DataClassificationRegistry()
        destinations = registry.list_destinations()
        assert len(destinations) >= 3
        names = {d["name"] for d in destinations}
        assert "analytics_warehouse" in names
        assert "operational_store" in names
        assert "data_marketplace" in names

    def test_register_custom(self):
        registry = DataClassificationRegistry()
        record = DestinationPolicyRecord(
            name="my_custom_bucket",
            policy=DestinationPolicy.STRICT,
            allowed_data_classes={DataClass.CUSTOM},
        )
        registry.register(record)
        assert registry.get("my_custom_bucket") is not None

    def test_validate_allowed_write(self):
        registry = DataClassificationRegistry()
        manifest = PurposeManifest(
            purpose="monitoring",
            data_class=DataClass.METRIC,
            owner="infra-team",
            destination="analytics_warehouse",
        )
        registry.validate_write(manifest)

    def test_validate_disallowed_data_class(self):
        registry = DataClassificationRegistry()
        manifest = PurposeManifest(
            purpose="secret_task",
            data_class=DataClass.TASK_RESULT,
            owner="dev-team",
            destination="analytics_warehouse",
        )
        import pytest
        with pytest.raises(DataClassNotAllowedError):
            registry.validate_write(manifest)

    def test_validate_unknown_destination(self):
        registry = DataClassificationRegistry()
        manifest = PurposeManifest(
            purpose="test",
            data_class=DataClass.LOG,
            owner="test",
            destination="nonexistent_bucket",
        )
        import pytest
        with pytest.raises(DestinationNotFoundError):
            registry.validate_write(manifest)


class TestIngestionPipeline:
    def test_successful_write(self):
        pipeline = IngestionPipeline()
        manifest = PurposeManifest(
            purpose="operational_monitoring",
            data_class=DataClass.METRIC,
            owner="platform-team",
            destination="analytics_warehouse",
        )
        result = pipeline.write(manifest, {"cpu": 0.85, "memory": 4096})
        assert result["status"] == "written"
        assert "write_id" in result
        assert result["payload_size_bytes"] > 0

    def test_blocked_write(self):
        pipeline = IngestionPipeline()
        manifest = PurposeManifest(
            purpose="unauthorized_reuse",
            data_class=DataClass.TASK_RESULT,
            owner="rogue-service",
            destination="analytics_warehouse",
        )
        result = pipeline.write(manifest, {"secret": "data"})
        assert result["status"] == "blocked"
        assert "DataClassNotAllowedError" in result["error"]

    def test_unknown_destination_blocked(self):
        pipeline = IngestionPipeline()
        manifest = PurposeManifest(
            purpose="test",
            data_class=DataClass.LOG,
            owner="test",
            destination="unknown_bucket",
        )
        result = pipeline.write(manifest, {"key": "value"})
        assert result["status"] == "blocked"
        assert "DestinationNotFoundError" in result["error"]

    def test_audit_log_records_all_writes(self):
        pipeline = IngestionPipeline()
        pipeline.write(
            PurposeManifest("metrics", DataClass.METRIC, "team-a", "analytics_warehouse"),
            {"value": 42},
        )
        pipeline.write(
            PurposeManifest("hack", DataClass.TASK_RESULT, "attacker", "analytics_warehouse"),
            {"leak": True},
        )
        report = pipeline.audit_report()
        assert len(report) == 2
        assert report[0]["success"] is True
        assert report[1]["success"] is False

    def test_audit_report_filter_by_purpose(self):
        pipeline = IngestionPipeline()
        pipeline.write(
            PurposeManifest("ops", DataClass.LOG, "team-a", "analytics_warehouse"),
            {"msg": "hello"},
        )
        pipeline.write(
            PurposeManifest("audit", DataClass.AUDIT, "sec-team", "analytics_warehouse"),
            {"event": "login"},
        )
        ops_entries = pipeline.audit_report(purpose="ops")
        assert len(ops_entries) == 1
        assert ops_entries[0]["manifest"]["purpose"] == "ops"

    def test_audit_report_filter_by_destination(self):
        pipeline = IngestionPipeline()
        pipeline.write(
            PurposeManifest("m1", DataClass.METRIC, "team-a", "analytics_warehouse"),
            {"v": 1},
        )
        pipeline.write(
            PurposeManifest("c1", DataClass.CUSTOM, "team-b", "data_marketplace"),
            {"v": 2},
        )
        marketplace = pipeline.audit_report(destination="data_marketplace")
        assert len(marketplace) == 1
        assert marketplace[0]["manifest"]["destination"] == "data_marketplace"

    def test_summary_counts(self):
        pipeline = IngestionPipeline()
        pipeline.write(
            PurposeManifest("m1", DataClass.METRIC, "t1", "analytics_warehouse"),
            {"a": 1},
        )
        pipeline.write(
            PurposeManifest("m2", DataClass.METRIC, "t1", "analytics_warehouse"),
            {"b": 2},
        )
        pipeline.write(
            PurposeManifest("bad", DataClass.TASK_RESULT, "t1", "analytics_warehouse"),
            {"c": 3},
        )
        summary = pipeline.summary()
        assert summary["total_writes"] == 3
        assert summary["successful_writes"] == 2
        assert summary["blocked_writes"] == 1

    def test_shared_instance_convenience_function(self):
        from src.common.data_lake import get_pipeline, write_with_purpose
        p1 = get_pipeline()
        p2 = get_pipeline()
        assert p1 is p2
        result = write_with_purpose(
            purpose="test_write",
            data_class="metric",
            owner="qa-team",
            destination="analytics_warehouse",
            payload={"test": True},
        )
        assert result["status"] == "written"

    def test_destination_to_dict(self):
        record = DestinationPolicyRecord(
            name="test",
            policy=DestinationPolicy.SHARED,
            allowed_data_classes={DataClass.LOG, DataClass.EVENT},
            description="test dest",
        )
        d = record.to_dict()
        assert d["name"] == "test"
        assert d["policy"] == "shared"
        assert sorted(d["allowed_data_classes"]) == ["event", "log"]


class TestPurposeManifest:
    def test_to_dict(self):
        manifest = PurposeManifest(
            purpose="test", data_class=DataClass.LOG, owner="dev",
            destination="lake", description="test write",
            retention_days=30, tags={"env": "prod"},
        )
        d = manifest.to_dict()
        assert d["purpose"] == "test"
        assert d["data_class"] == "log"
        assert d["owner"] == "dev"
        assert d["destination"] == "lake"
        assert d["retention_days"] == 30
        assert d["tags"] == {"env": "prod"}


class TestDataLakeWrite:
    def test_to_dict(self):
        manifest = PurposeManifest("p", DataClass.EVENT, "o", "d")
        record = DataLakeWrite(manifest, 100, True)
        d = record.to_dict()
        assert d["success"] is True
        assert d["payload_size"] == 100
        assert d["manifest"]["purpose"] == "p"
        assert "timestamp" in d
