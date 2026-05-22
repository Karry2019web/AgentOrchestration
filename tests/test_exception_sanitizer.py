"""Tests for exception context sanitizer."""
import pytest
from src.common.exception_sanitizer import (
    sanitize_exception_context,
    format_exception_event,
    _sanitize_value,
    _is_safe_field,
)


class TestIsSafeField:
    def test_safe_fields(self):
        assert _is_safe_field("task_id") is True
        assert _is_safe_field("error_type") is True
        assert _is_safe_field("agent_id") is True
        assert _is_safe_field("reason") is True

    def test_unsafe_fields(self):
        assert _is_safe_field("payload") is False
        assert _is_safe_field("raw_data") is False
        assert _is_safe_field("request_body") is False
        assert _is_safe_field("local_vars") is False

    def test_unknown_fields_default_to_safe(self):
        assert _is_safe_field("some_random_key") is True
        assert _is_safe_field("count") is True


class TestSanitizeValue:
    def test_scalar_preserved(self):
        assert _sanitize_value(42) == 42
        assert _sanitize_value("hello") == "hello"
        assert _sanitize_value(True) is True
        assert _sanitize_value(None) is None

    def test_long_string_truncated(self):
        long_str = "a" * 1000
        result = _sanitize_value(long_str)
        assert len(result) < 300
        assert result.endswith("...")

    def test_dict_safe_fields_preserved(self):
        d = {"task_id": "abc", "agent_id": "xyz", "error": "boom"}
        result = _sanitize_value(d)
        assert result == {"task_id": "abc", "agent_id": "xyz", "error": "boom"}

    def test_dict_unsafe_fields_summarized(self):
        d = {"payload": {"secret": "data"}, "task_id": "safe"}
        result = _sanitize_value(d)
        assert result["task_id"] == "safe"
        assert "payload" in result
        assert isinstance(result["payload"], str)

    def test_long_list_summarized(self):
        result = _sanitize_value([1, 2, 3, 4, 5, 6])
        assert result == ["<6 items>"]


class TestSanitizeExceptionContext:
    def test_empty_context(self):
        result = sanitize_exception_context()
        assert result == {}

    def test_with_identifiers(self):
        result = sanitize_exception_context(
            task_id="t-1", execution_id="e-1", agent_id="a-1"
        )
        assert result["task_id"] == "t-1"
        assert result["execution_id"] == "e-1"
        assert result["agent_id"] == "a-1"

    def test_context_with_payload(self):
        ctx = {"payload": {"name": "attack", "cmd": "rm -rf /"}, "task_id": "t-1"}
        result = sanitize_exception_context(context=ctx, task_id="t-1")
        assert result["task_id"] == "t-1"
        assert "payload" in result["context"]
        assert isinstance(result["context"]["payload"], str)
        assert "rm" not in result["context"]["payload"]


class TestFormatExceptionEvent:
    def test_basic_event(self):
        exc = ValueError("invalid input")
        event = format_exception_event(exc, task_id="t-1")
        assert event["error_type"] == "ValueError"
        assert event["error"] == "invalid input"
        assert event["context"]["task_id"] == "t-1"

    def test_no_raw_payload(self):
        exc = RuntimeError("fail")
        event = format_exception_event(
            exc,
            context={"payload": {"secret": "hunter2"}},
            task_id="t-1",
        )
        assert event["error_type"] == "RuntimeError"
        assert event["context"]["task_id"] == "t-1"
        assert "hunter2" not in str(event)

    def test_supports_error_dashboard_lookup(self):
        exc = KeyError("agent-42")
        event = format_exception_event(exc, task_id="agent-42")
        assert event["error_type"] == "KeyError"
        assert event["context"]["task_id"] == "agent-42"
