"""Tests for data lake ingestion with purpose limitation enforcement."""

import pytest
from uuid import UUID

from src.data.classification import (
    DataClass,
    DataClassificationRegistry,
    DestinationPolicy,
)
from src.data.lake import (
    DataLakeIngestor,
    IngestionManifest,
    IngestionStatus,
)
from src.data.audit import AuditReporter


class TestDataClassificationRegistry:
    def setup_method(self):
        self.registry = DataClassificationRegistry()

    def test_default_policies_exist(self):
        assert len(self.registry.known_destinations) >= 3

    def test_is_destination_allowed_approved(self):
        assert self.registry.is_destination_allowed("analytics_store", DataClass.ANALYTICAL)

    def test_is_destination_allowed_rejected(self):
        assert not self.registry.is_destination_allowed("analytics_store", DataClass.PII)

    def test_unknown_destination_rejected(self):
        assert not self.registry.is_destination_allowed("unknown_sink", DataClass.OPERATIONAL)

    def test_list_destinations_for_class(self):
        dests = self.registry.list_destinations_for_class(DataClass.OPERATIONAL)
        assert "analytics_store" in dests
        assert "operational_log" in dests

    def test_register_custom_policy(self):
        policy = DestinationPolicy(
            destination="custom_sink",
            allowed_classes={DataClass.FINANCIAL},
        )
        self.registry.register_policy(policy)
        assert self.registry.is_destination_allowed("custom_sink", DataClass.FINANCIAL)
        assert not self.registry.is_destination_allowed("custom_sink", DataClass.PII)


class TestDataLakeIngestor:
    def setup_method(self):
        self.ingestor = DataLakeIngestor()

    def test_ingest_approved(self):
        manifest = IngestionManifest(
            purpose="monthly aggregation",
            data_class=DataClass.ANALYTICAL,
            owner="data-team",
            destination="analytics_store",
        )
        result = self.ingestor.ingest(manifest)
        assert result.status == IngestionStatus.APPROVED
        assert result.reason == "Approved by policy"

    def test_ingest_rejected_destination_mismatch(self):
        manifest = IngestionManifest(
            purpose="user profile export",
            data_class=DataClass.PII,
            owner="compliance",
            destination="operational_log",
        )
        result = self.ingestor.ingest(manifest)
        assert result.status == IngestionStatus.REJECTED
        assert "not approved" in result.reason
        assert len(result.approved_destinations) > 0

    def test_ingest_rejected_empty_purpose(self):
        manifest = IngestionManifest(
            purpose="",
            data_class=DataClass.OPERATIONAL,
            owner="ops",
            destination="operational_log",
        )
        result = self.ingestor.ingest(manifest)
        assert result.status == IngestionStatus.REJECTED
        assert "Purpose" in result.reason

    def test_ingest_rejected_unknown_destination(self):
        manifest = IngestionManifest(
            purpose="ad hoc query",
            data_class=DataClass.ANALYTICAL,
            owner="analyst",
            destination="shadow_bucket",
        )
        result = self.ingestor.ingest(manifest)
        assert result.status == IngestionStatus.REJECTED
        assert "not approved" in result.reason

    def test_ingest_batch_mixed(self):
        approved = IngestionManifest(
            purpose="batch test approved",
            data_class=DataClass.OPERATIONAL,
            owner="tests",
            destination="operational_log",
        )
        rejected = IngestionManifest(
            purpose="batch test rejected",
            data_class=DataClass.PII,
            owner="tests",
            destination="operational_log",
        )
        results = self.ingestor.ingest_batch([approved, rejected])
        assert len(results) == 2
        assert results[0].status == IngestionStatus.APPROVED
        assert results[1].status == IngestionStatus.REJECTED

    def test_history_tracks_approved_only(self):
        manifest = IngestionManifest(
            purpose="history check",
            data_class=DataClass.ANALYTICAL,
            owner="qa",
            destination="analytics_store",
        )
        self.ingestor.ingest(manifest)
        history = self.ingestor.get_history()
        assert len(history) == 1

    def test_ingest_custom_registry(self):
        policy = DestinationPolicy(
            destination="all_purpose",
            allowed_classes={DataClass.OPERATIONAL, DataClass.ANALYTICAL, DataClass.PII},
        )
        reg = DataClassificationRegistry(policies={"all_purpose": policy})
        ingestor = DataLakeIngestor(registry=reg)

        manifest = IngestionManifest(
            purpose="cross-class test",
            data_class=DataClass.PII,
            owner="compliance",
            destination="all_purpose",
        )
        result = ingestor.ingest(manifest)
        assert result.status == IngestionStatus.APPROVED


class TestAuditReporter:
    def setup_method(self):
        self.registry = DataClassificationRegistry()
        self.ingestor = DataLakeIngestor(registry=self.registry)
        self.audit = AuditReporter()

    def _ingest_and_audit(self, purpose: str, data_class: DataClass,
                          destination: str, owner: str = "test-user"):
        manifest = IngestionManifest(
            purpose=purpose,
            data_class=data_class,
            owner=owner,
            destination=destination,
        )
        result = self.ingestor.ingest(manifest)
        return self.audit.record(manifest, result)

    def test_audit_records_accepted(self):
        entry = self._ingest_and_audit("audit test", DataClass.ANALYTICAL,
                                        "analytics_store")
        assert entry.status == IngestionStatus.APPROVED.value
        assert entry.manifest_id is not None

    def test_audit_records_rejected(self):
        entry = self._ingest_and_audit("audit reject test", DataClass.PII,
                                        "operational_log")
        assert entry.status == IngestionStatus.REJECTED.value

    def test_report_by_purpose(self):
        self._ingest_and_audit("report-test", DataClass.OPERATIONAL, "operational_log")
        self._ingest_and_audit("report-test", DataClass.ANALYTICAL, "analytics_store")
        self._ingest_and_audit("other-task", DataClass.ANALYTICAL, "analytics_store")
        entries = self.audit.report_by_purpose("report-test")
        assert len(entries) == 2

    def test_report_by_owner(self):
        self._ingest_and_audit("owner test", DataClass.OPERATIONAL,
                                "operational_log", owner="alice")
        self._ingest_and_audit("owner test 2", DataClass.ANALYTICAL,
                                "analytics_store", owner="alice")
        self._ingest_and_audit("bob task", DataClass.ANALYTICAL,
                                "analytics_store", owner="bob")
        entries = self.audit.report_by_owner("alice")
        assert len(entries) == 2

    def test_report_by_data_class(self):
        self._ingest_and_audit("class test", DataClass.OPERATIONAL, "operational_log")
        self._ingest_and_audit("class test 2", DataClass.OPERATIONAL, "analytics_store")
        self._ingest_and_audit("class test 3", DataClass.ANALYTICAL, "analytics_store")
        entries = self.audit.report_by_data_class(DataClass.OPERATIONAL)
        assert len(entries) == 2

    def test_full_report(self):
        self._ingest_and_audit("full1", DataClass.OPERATIONAL, "operational_log")
        self._ingest_and_audit("full2", DataClass.ANALYTICAL, "analytics_store")
        report = self.audit.full_report()
        assert len(report) == 2

    def test_summary(self):
        self._ingest_and_audit("sum1", DataClass.OPERATIONAL, "operational_log")
        self._ingest_and_audit("sum2", DataClass.ANALYTICAL, "analytics_store")
        # Rejected write
        manifest = IngestionManifest(
            purpose="sum3", data_class=DataClass.PII,
            owner="test", destination="operational_log",
        )
        result = self.ingestor.ingest(manifest)
        self.audit.record(manifest, result)
        summary = self.audit.summary()
        assert summary["total_entries"] == 3
        assert summary["accepted"] == 2
        assert summary["rejected"] == 1
        assert "operational_log" in summary["by_destination"]
        assert "analytics_store" in summary["by_destination"]
