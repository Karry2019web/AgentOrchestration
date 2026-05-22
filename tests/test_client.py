"""Tests for the OrchestratorClient SDK."""

import json
import pytest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from src.sdk.client import OrchestratorClient


class TestOrchestratorClient:
    def setup_method(self):
        self.client = OrchestratorClient(
            base_url="https://test.api",
            api_key="test-key-123"
        )

    def test_http_error_includes_method_and_path(self):
        """HTTPError responses should include safe method and path context."""
        with patch("src.sdk.client.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "/api/v2/agents", 500, "Internal Server Error", {}, None
            )
            result = self.client._request("GET", "/agents")
            assert result["method"] == "GET"
            assert result["path"] == "/agents"
            assert result["error"] == 500

    def test_url_error_includes_method_and_path(self):
        """URLError (connection errors) should include safe method and path."""
        with patch("src.sdk.client.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Connection refused")
            result = self.client._request("POST", "/agents")
            assert result["method"] == "POST"
            assert result["path"] == "/agents"
            assert result["error"] == "connection_error"

    def test_os_error_includes_method_and_path(self):
        """OS-level transport errors should include safe method and path."""
        with patch("src.sdk.client.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError("Name or service not known")
            result = self.client._request("DELETE", "/agents/abc-123")
            assert result["method"] == "DELETE"
            assert result["path"] == "/agents/abc-123"
            assert result["error"] == "transport_error"

    def test_register_agent_success(self):
        """Normal registration returns the expected result."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": "agent-1"}).encode()
        mock_resp.__enter__.return_value = mock_resp
        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            result = self.client.register_agent("test-agent", "worker.processor")
            assert result["id"] == "agent-1"
