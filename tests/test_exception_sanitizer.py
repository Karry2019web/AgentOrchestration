"""Tests for exception context sanitizer."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.common.exception_sanitizer import (
    _is_safe_field,
    _sanitize_value,
    _summarize,
    sanitize_exception_context,
    format_exception_event,
)


class TestIsSafeField:
    def test_safe_fields_pass(self):
        assert _is_safe_field("task_id") is True
        assert _is_safe_field("error_type") is True
        assert _is_safe_field("status_code") is True
        assert _is_safe_field("timestamp") is True

    def test_unsafe_fields_blocked(self):
        assert _is_safe_field("payload") is False
        assert _is_safe_field("secret_key") is False
        assert _is_safe_field("auth_token") is False
        assert _is_safe_field("raw_data") is False
        assert _is_safe_field("password") is False

    def test_unknown_fields_default_safe(self):
        assert _is_safe_field("custom_field_xyz") is True
        assert _is_safe_field("random_name") is True
        assert _is_safe_field("foobar") is True


class TestSummarize:
    def test_none(self):
        assert _summarize(None) == "<null>"

    def test_empty_string(self):
        assert _summarize("") == "<empty str>"

    def test_short_string(self):
        assert _summarize("hello") == "<str: hello>"

    def test_long_string(self):
        long_str = "x" * 100
        result = _summarize(long_str)
        assert result.startswith("<str:")
        assert len(result) < 80

    def test_integer(self):
        result = _summarize(42)
        assert "<int: 42>" in result or result == "<int: 42>"


class TestSanitizeValue:
    def test_scalars_preserved(self):
        assert _sanitize_value(42) == 42
        assert _sanitize_value(3.14) == 3.14
        assert _sanitize_value(True) is True
        assert _sanitize_value(None) is None

    def test_string_truncated(self):
        s = "a" * 300
        result = _sanitize_value(s)
        assert len(result) <= 203  # 200 + "..."
        assert result.endswith("...")

    def test_safe_dict_fields(self):
        d = {"task_id": "t-123", "status_code": 200}
        result = _sanitize_value(d)
        assert result["task_id"] == "t-123"
        assert result["status_code"] == 200

    def test_unsafe_dict_field(self):
        d = {"payload": {"secret": "data"}}
        result = _sanitize_value(d)
        assert isinstance(result["payload"], str)
        assert "<" in result["payload"]

    def test_long_list(self):
        result = _sanitize_value([1, 2, 3, 4, 5, 6, 7])
        assert result == ["<7 items>"]


class TestSanitizeExceptionContext:
    def test_empty(self):
        result = sanitize_exception_context()
        assert result == {}

    def test_with_identifiers(self):
        result = sanitize_exception_context(
            task_id="t-123", execution_id="e-456", agent_id="a-789"
        )
        assert result == {
            "task_id": "t-123",
            "execution_id": "e-456",
            "agent_id": "a-789",
        }

    def test_context_with_raw_payload_sanitized(self):
        ctx = {"payload": {"secret": "data"}, "task_id": "t-123"}
        result = sanitize_exception_context(ctx)
        # payload should be summarized
        assert isinstance(result.get("context", {}).get("payload"), str)
        assert "<" in result["context"]["payload"]


class TestFormatExceptionEvent:
    def test_basic_exception(self):
        try:
            raise ValueError("test error")
        except ValueError as e:
            event = format_exception_event(e)
            assert event["error_type"] == "ValueError"
            assert event["error"] == "test error"

    def test_no_raw_payload_in_event(self):
        try:
            raise RuntimeError("task failed")
        except RuntimeError as e:
            event = format_exception_event(
                e, context={"payload": {"key": "secret"}},
                task_id="t-123"
            )
            assert event["error_type"] == "RuntimeError"
            assert event["error"] == "task failed"
            assert "context" in event
            assert event["context"]["task_id"] == "t-123"
            # payload should be sanitized, not raw
            assert isinstance(event["context"].get("context", {}).get("payload"), str)

    def test_error_dashboard_lookup(self):
        try:
            raise KeyError("missing_field")
        except KeyError as e:
            event = format_exception_event(
                e, task_id="t-999", execution_id="e-888"
            )
            assert event["context"]["task_id"] == "t-999"
            assert event["context"]["execution_id"] == "e-888"
