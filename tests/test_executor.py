import pytest
from src.common.metrics import (
    validate_schema_version,
    UnsupportedSchemaVersion,
    apply_export_metadata,
    SCHEMA_VERSION,
)


class TestExecutorExports:
    def test_execution_result_includes_schema_version(self):
        raw = {
            "execution_id": "exec-1",
            "agent_id": "agent-1",
            "task_id": "task-1",
            "result": "ok",
            "duration": 0.5,
            "timestamp": 1234567890.0,
        }
        wrapped = apply_export_metadata(raw)
        assert wrapped["schema_version"] == SCHEMA_VERSION
        assert wrapped["data"]["execution_id"] == "exec-1"
        assert wrapped["data"]["result"] == "ok"

    def test_execution_result_validates_ok(self):
        raw = {"agent_id": "a1"}
        wrapped = apply_export_metadata(raw)
        assert validate_schema_version(wrapped) is True

    def test_execution_result_rejects_old_version(self):
        wrapped = {"schema_version": "0.1.0", "data": {"agent_id": "a1"}}
        with pytest.raises(UnsupportedSchemaVersion):
            validate_schema_version(wrapped)

    def test_execution_result_rejects_missing_version(self):
        with pytest.raises(UnsupportedSchemaVersion):
            validate_schema_version({"data": {"x": 1}})
