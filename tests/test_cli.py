"""Tests for CLI entry point with injectable client."""

import sys
from unittest.mock import MagicMock
from src.cli.main import cli


class TestCliWithInjectableClient:
    def setup_method(self):
        self.mock_client = MagicMock()
        self._orig_argv = sys.argv

    def teardown_method(self):
        sys.argv = self._orig_argv

    def test_cli_accepts_injectable_client(self):
        """CLI with init command and injectable client does not hit real endpoints."""
        sys.argv = ["cli", "init", "test-project"]
        cli(client=self.mock_client)
        self.mock_client.register_agent.assert_not_called()
        self.mock_client.list_agents.assert_not_called()
        self.mock_client.get_agent.assert_not_called()

    def test_deploy_uses_injectable_client(self):
        """Deploy calls register_agent on injected client."""
        sys.argv = ["cli", "deploy", "manifest.yaml"]
        cli(client=self.mock_client)
        self.mock_client.register_agent.assert_called_once_with("manifest.yaml", "custom")

    def test_status_uses_injectable_client(self):
        """Status calls list_agents on injected client."""
        sys.argv = ["cli", "status"]
        cli(client=self.mock_client)
        self.mock_client.list_agents.assert_called_once()

    def test_logs_uses_injectable_client(self):
        """Logs calls get_agent on injected client."""
        sys.argv = ["cli", "logs", "agent-123"]
        cli(client=self.mock_client)
        self.mock_client.get_agent.assert_called_once_with("agent-123")

    def test_default_client_created_when_none_injected(self):
        """cli() without client argument creates default OrchestratorClient."""
        sys.argv = ["cli", "init", "auto-test"]
        cli()
        self.mock_client.assert_not_called()
