import pytest
from src.sdk.client import OrchestratorClient


class TestOrchestratorClient:
    def test_register_agent_with_valid_name(self, monkeypatch):
        """Valid agent names should proceed to request."""
        client = OrchestratorClient(base_url="http://test", api_key="test-key")
        calls = []

        def mock_request(method, path, data):
            calls.append((method, path, data))
            return {"id": "agent-1"}

        monkeypatch.setattr(client, "_request", mock_request)
        result = client.register_agent("my-agent", "worker.processor", {"key": "val"})
        assert result == {"id": "agent-1"}
        assert len(calls) == 1
        method, path, data = calls[0]
        assert method == "POST"
        assert path == "/agents"
        assert data["name"] == "my-agent"

    def test_register_agent_trims_whitespace(self, monkeypatch):
        """Names with surrounding whitespace should be trimmed before sending."""
        client = OrchestratorClient(base_url="http://test", api_key="test-key")
        calls = []

        def mock_request(method, path, data):
            calls.append((method, path, data))
            return {"id": "agent-1"}

        monkeypatch.setattr(client, "_request", mock_request)
        result = client.register_agent("  my-agent  ", "worker.processor")
        assert result == {"id": "agent-1"}
        assert calls[0][2]["name"] == "my-agent"

    def test_register_agent_rejects_empty_name(self):
        """Empty name should raise ValueError."""
        client = OrchestratorClient(base_url="http://test", api_key="test-key")
        with pytest.raises(ValueError, match="Agent name must not be empty or whitespace-only"):
            client.register_agent("", "worker.processor")

    def test_register_agent_rejects_none_name(self):
        """None name should raise ValueError."""
        client = OrchestratorClient(base_url="http://test", api_key="test-key")
        with pytest.raises(ValueError, match="Agent name must not be empty or whitespace-only"):
            client.register_agent(None, "worker.processor")  # type: ignore

    def test_register_agent_rejects_whitespace_only_name(self):
        """Whitespace-only name should raise ValueError."""
        client = OrchestratorClient(base_url="http://test", api_key="test-key")
        with pytest.raises(ValueError, match="Agent name must not be empty or whitespace-only"):
            client.register_agent("   ", "worker.processor")
