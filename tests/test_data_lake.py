"""Tests for data lake purpose-limited ingestion."""
import sys
from unittest.mock import MagicMock
sys.modules["resource"] = MagicMock()
import src.agent
src.agent.AgentStatus = MagicMock()
src.agent.AgentRegistry = MagicMock()

import pytest
from src.orchestrator.data_lake import (
    ClassificationRegistry,
    GovernedPipeline,
    Manifest,
    PolicyError,
)


class TestClassificationRegistry:

    def test_allows_approved_classification(self):
        reg = ClassificationRegistry()
        reg.allow("analytics-curated", "operational", "aggregate")
        assert reg.check("analytics-curated", "operational") is True
        assert reg.check("analytics-curated", "aggregate") is True

    def test_rejects_unapproved_classification(self):
        reg = ClassificationRegistry()
        reg.allow("analytics-curated", "operational")
        assert reg.check("analytics-curated", "pii") is False

    def test_rejects_unknown_destination(self):
        reg = ClassificationRegistry()
        assert reg.check("unknown-bucket", "operational") is False

    def test_allow_requires_non_blank_classification(self):
        reg = ClassificationRegistry()
        with pytest.raises(PolicyError):
            reg.allow("dest", "")

    def test_case_insensitive(self):
        reg = ClassificationRegistry()
        reg.allow("BIG-DATA", "SENSITIVE")
        assert reg.check("big-data", "sensitive") is True


class TestGovernedPipeline:

    @pytest.fixture
    def pipeline(self):
        reg = ClassificationRegistry()
        reg.allow("analytics-curated", "operational", "aggregate")
        reg.allow("audit-store", "audit-log")
        return GovernedPipeline(reg)

    def test_writes_with_approved_manifest(self, pipeline):
        manifest = Manifest(
            purpose="ops-reporting",
            classification="operational",
            owner="platform-team",
            destination="analytics-curated",
        )
        entry = pipeline.write("events/task-1.json", {"task_id": 1}, manifest)
        assert entry.approved is True
        assert pipeline.read("events/task-1.json") == {"task_id": 1}

    def test_rejects_unapproved_destination(self, pipeline):
        manifest = Manifest(
            purpose="reporting", classification="pii",
            owner="team", destination="analytics-curated",
        )
        with pytest.raises(PolicyError, match="does not allow"):
            pipeline.write("events/pii.json", {"ssn": "123"}, manifest)

    def test_rejects_blank_fields(self, pipeline):
        with pytest.raises(PolicyError, match="must not be blank"):
            pipeline.write("events/bad.json", {},
                           Manifest("", "operational", "team", "dest"))

    def test_audit_records_approved_writes(self, pipeline):
        manifest = Manifest(
            purpose="audit", classification="audit-log",
            owner="auditor", destination="audit-store",
        )
        pipeline.write("audit/001.json", {"event": "login"}, manifest)
        entries = pipeline.list_audit(owner="auditor")
        assert len(entries) == 1
        assert entries[0]["approved"] is True

    def test_audit_records_rejected_writes(self, pipeline):
        manifest = Manifest(
            purpose="x", classification="pii",
            owner="bob", destination="audit-store",
        )
        with pytest.raises(PolicyError):
            pipeline.write("x.json", {}, manifest)
        entries = pipeline.list_audit(owner="bob")
        assert len(entries) == 1
        assert entries[0]["approved"] is False

    def test_audit_filter_by_purpose(self, pipeline):
        m1 = Manifest("ops", "operational", "alice", "analytics-curated")
        m2 = Manifest("audit", "audit-log", "alice", "audit-store")
        pipeline.write("a.json", {}, m1)
        pipeline.write("b.json", {}, m2)
        ops_entries = pipeline.list_audit(purpose="ops")
        assert len(ops_entries) == 1
        assert ops_entries[0]["key"] == "a.json"

    def test_read_returns_none_for_missing_key(self, pipeline):
        assert pipeline.read("nonexistent") is None
