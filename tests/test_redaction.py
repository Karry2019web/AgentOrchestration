"""Tests for shared redaction policy across export formats."""

import json
import pytest
from src.common.redaction import (
    FieldClassification,
    RedactionPolicy,
    RedactionSerializer,
    DEFAULT_POLICIES,
)


class TestFieldClassification:
    """Field classifications are correct."""

    def test_public_returns_value(self):
        policy = RedactionPolicy("test_field", FieldClassification.PUBLIC)
        assert policy.redact_value("hello") == "hello"
        assert policy.redact_value(42) == 42
        assert policy.redact_value(None) is None

    def test_internal_returns_value(self):
        policy = RedactionPolicy("test_field", FieldClassification.INTERNAL)
        assert policy.redact_value("internal-data") == "internal-data"

    def test_restricted_masks_value(self):
        policy = RedactionPolicy("test_field", FieldClassification.RESTRICTED)
        assert policy.redact_value("abcdefgh") == "abcd****"
        assert policy.redact_value("ab") == "****"

    def test_sensitive_omits_value(self):
        policy = RedactionPolicy("test_field", FieldClassification.SENSITIVE)
        assert policy.redact_value("anything") == "[REDACTED]"

    def test_restricted_with_condition(self):
        policy = RedactionPolicy(
            "conditional", FieldClassification.RESTRICTED,
            redact_if=lambda v: len(str(v)) > 3,
        )
        assert policy.redact_value("ab") == "ab"
        assert policy.redact_value("abcdef") == "abcd****"


class TestDefaultPolicies:
    """Default policies cover expected fields."""

    def test_sensitive_fields_are_redacted(self):
        serializer = RedactionSerializer()
        assert serializer.redact_field("api_key", "sk-12345") == "[REDACTED]"
        assert serializer.redact_field("password", "hunter2") == "[REDACTED]"
        assert serializer.redact_field("secret", "my-secret") == "[REDACTED]"
        assert serializer.redact_field("stack_trace", "File X, line Y") == "[REDACTED]"

    def test_restricted_fields_are_masked(self):
        serializer = RedactionSerializer()
        val = serializer.redact_field("token", "ghp_abc123def456")
        assert val != "ghp_abc123def456"
        assert "[REDACTED]" not in str(val)
        assert val is not None

    def test_public_fields_pass_through(self):
        serializer = RedactionSerializer()
        assert serializer.redact_field("agent_name", "my-agent") == "my-agent"
        assert serializer.redact_field("workflow_id", "wf-123") == "wf-123"
        assert serializer.redact_field("task_id", "t-456") == "t-456"
        assert serializer.redact_field("status", "completed") == "completed"

    def test_unknown_field_defaults_to_public(self):
        serializer = RedactionSerializer()
        assert serializer.redact_field("nonexistent", "anything") == "anything"


class TestRedactionSerializer:
    """RedactionSerializer applies policy consistency across formats."""

    def test_serialize_redacts_sensitive_fields(self):
        serializer = RedactionSerializer()
        record = {
            "agent_name": "worker-1",
            "api_key": "sk-secret",
            "status": "running",
            "token": "ghp_abc123",
        }
        safe = serializer.serialize(record)
        assert safe["agent_name"] == "worker-1"
        assert safe["status"] == "running"
        assert safe["api_key"] == "[REDACTED]"
        assert "abc123" not in str(safe)

    def test_serialize_preserves_original(self):
        """Original data is not mutated by serialize()."""
        serializer = RedactionSerializer()
        original = {"agent_name": "test", "api_key": "secret"}
        safe = serializer.serialize(original)
        assert original["api_key"] == "secret"

    def test_serialize_many(self):
        serializer = RedactionSerializer()
        records = [
            {"agent_name": "a1", "api_key": "sk-1"},
            {"agent_name": "a2", "api_key": "sk-2"},
        ]
        safe = serializer.serialize_many(records)
        assert len(safe) == 2
        for s in safe:
            assert s["api_key"] == "[REDACTED]"

    def test_json_output_redacts_sensitive_data(self):
        """JSON serialization of redacted records does not leak sensitive data."""
        serializer = RedactionSerializer()
        record = {"agent_name": "worker-1", "password": "hunter2"}
        safe = serializer.serialize(record)
        json_str = json.dumps(safe)
        assert "hunter2" not in json_str
        assert "[REDACTED]" in json_str

    def test_custom_policy_overrides_default(self):
        custom_policy = RedactionPolicy("agent_name", FieldClassification.RESTRICTED)
        serializer = RedactionSerializer(policies={"agent_name": custom_policy})
        assert serializer.redact_field("agent_name", "visible-agent") != "visible-agent"

    def test_register_new_field(self):
        serializer = RedactionSerializer()
        serializer.register_policy(
            RedactionPolicy("custom_field", FieldClassification.SENSITIVE)
        )
        assert serializer.redact_field("custom_field", "anything") == "[REDACTED]"

    def test_get_policy_returns_policy(self):
        serializer = RedactionSerializer()
        policy = serializer.get_policy("token")
        assert policy is not None
        assert policy.field_name == "token"

    def test_get_policy_unknown_returns_none(self):
        serializer = RedactionSerializer()
        assert serializer.get_policy("does_not_exist") is None

    def test_classify_known_field(self):
        serializer = RedactionSerializer()
        assert serializer.classify("api_key") == FieldClassification.SENSITIVE
        assert serializer.classify("agent_name") == FieldClassification.PUBLIC
        assert serializer.classify("token") == FieldClassification.RESTRICTED

    def test_classify_unknown_field_is_public(self):
        serializer = RedactionSerializer()
        assert serializer.classify("foo") == FieldClassification.PUBLIC

    def test_error_message_is_masked(self):
        serializer = RedactionSerializer()
        val = serializer.redact_field("error_message", "Something went wrong")
        assert val != "Something went wrong"
        assert val is not None

    def test_internal_ip_present(self):
        serializer = RedactionSerializer()
        val = serializer.redact_field("internal_ip", "10.0.0.1")
        assert val == "10.0.0.1"

    def test_serialize_with_none_value(self):
        serializer = RedactionSerializer()
        safe = serializer.serialize({"agent_name": None, "api_key": None})
        # None values should be preserved, not crash
        assert safe["api_key"] == "[REDACTED]"
        assert safe["agent_name"] is None


class TestExportConsistency:
    """All export formats use the same redaction policy."""

    def test_ui_and_json_redact_same_fields(self):
        """A field classified as SENSITIVE is hidden in all formats."""
        serializer = RedactionSerializer()
        record = {"agent_name": "test", "api_key": "secret-key"}
        safe = serializer.serialize(record)

        json_out = json.dumps(safe)
        assert "[REDACTED]" in json_out
        assert "secret-key" not in json_out

        ui_out = str(safe)
        assert "[REDACTED]" in ui_out
        assert "secret-key" not in ui_out
