"""Tests for AgentRuntime model routing fallback guard."""

import os
import pytest
from src.agent.runtime import (
    AgentRuntime,
    RuntimeState,
    ModelMode,
    UnsupportedModelModeError,
    resolve_model_mode,
    VALID_MODEL_MODES,
    DEFAULT_FALLBACK_MODE,
)


class TestModelModeValidation:
    """Tests for model mode resolution and fallback."""

    def test_valid_chat_mode(self):
        """Chat is a valid mode and resolves as-is."""
        assert resolve_model_mode("chat") == "chat"

    def test_valid_completion_mode(self):
        """Completion is a valid mode and resolves as-is."""
        assert resolve_model_mode("completion") == "completion"

    def test_valid_embedding_mode(self):
        """Embedding is a valid mode and resolves as-is."""
        assert resolve_model_mode("embedding") == "embedding"

    def test_valid_rerank_mode(self):
        """Rerank is a valid mode and resolves as-is."""
        assert resolve_model_mode("rerank") == "rerank"

    def test_valid_tools_mode(self):
        """Tools is a valid mode and resolves as-is."""
        assert resolve_model_mode("tools") == "tools"

    def test_all_valid_modes_are_in_set(self):
        """Every ModelMode member is present in VALID_MODEL_MODES."""
        for mode in ModelMode:
            assert mode.value in VALID_MODEL_MODES

    def test_unsupported_mode_falls_back_to_chat(self):
        """Unsupported mode string falls back to chat (default)."""
        result = resolve_model_mode("vision")
        assert result == DEFAULT_FALLBACK_MODE
        assert result == "chat"

    def test_empty_mode_falls_back_to_chat(self):
        """Empty mode string falls back to chat."""
        result = resolve_model_mode("")
        assert result == DEFAULT_FALLBACK_MODE

    def test_case_sensitive_modes(self):
        """Mode resolution is case-sensitive -- uppercase is unsupported."""
        result = resolve_model_mode("CHAT")
        assert result == DEFAULT_FALLBACK_MODE

    def test_random_string_falls_back(self):
        """Arbitrary string falls back to default mode."""
        result = resolve_model_mode("unknown_mode_123")
        assert result == DEFAULT_FALLBACK_MODE

    def test_whitespace_mode_falls_back(self):
        """Whitespace-only mode is unsupported and falls back."""
        result = resolve_model_mode("   ")
        assert result == DEFAULT_FALLBACK_MODE


class TestModelModeEnum:
    """Tests for ModelMode enum members."""

    def test_model_mode_values(self):
        """All ModelMode enum values are as expected."""
        assert ModelMode.CHAT.value == "chat"
        assert ModelMode.COMPLETION.value == "completion"
        assert ModelMode.EMBEDDING.value == "embedding"
        assert ModelMode.RERANK.value == "rerank"
        assert ModelMode.TOOLS.value == "tools"

    def test_model_mode_count(self):
        """There are exactly 5 supported model modes."""
        assert len(ModelMode) == 5

    def test_default_fallback_is_chat(self):
        """The default fallback mode is chat."""
        assert DEFAULT_FALLBACK_MODE == "chat"
        assert DEFAULT_FALLBACK_MODE == ModelMode.CHAT.value


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_valid_model_modes_contains_all_modes(self):
        """VALID_MODEL_MODES contains exactly the 5 valid modes."""
        expected = {"chat", "completion", "embedding", "rerank", "tools"}
        assert VALID_MODEL_MODES == expected

    def test_valid_model_modes_contains_only_valid(self):
        """VALID_MODEL_MODES rejects invalid modes."""
        assert "chat" in VALID_MODEL_MODES
        assert "vision" not in VALID_MODEL_MODES
        assert "unknown" not in VALID_MODEL_MODES


class TestUnsupportedModelModeError:
    """Tests for UnsupportedModelModeError exception."""

    def test_exception_is_raised_by_type(self):
        """UnsupportedModelModeError can be raised and caught."""
        with pytest.raises(UnsupportedModelModeError):
            raise UnsupportedModelModeError("unsupported mode")

    def test_exception_inherits_from_exception(self):
        """UnsupportedModelModeError is a valid Exception subclass."""
        assert issubclass(UnsupportedModelModeError, Exception)
