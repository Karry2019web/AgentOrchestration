"""Tests for DNS failure handling."""

import socket
from unittest.mock import patch, MagicMock
from urllib.error import URLError
import pytest
from src.sdk.client import DNSFailureHandler, _resolve_hostname, OrchestratorClient


class TestResolveHostname:
    def test_resolve_success(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]):
            result = _resolve_hostname("https://api.example.com/v1/test")
        assert result is not None

    def test_resolve_failure(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror):
            result = _resolve_hostname("https://nonexistent.invalid")
            assert result is None

    def test_resolve_os_error(self):
        with patch("socket.getaddrinfo", side_effect=OSError):
            result = _resolve_hostname("https://bad.example.com")
            assert result is None


class TestDNSFailureHandler:
    def setup_method(self):
        DNSFailureHandler.reset()

    def test_initial_state(self):
        assert not DNSFailureHandler.is_open("example.com")

    def test_failure_threshold_not_reached(self):
        DNSFailureHandler.record_failure("example.com")
        DNSFailureHandler.record_failure("example.com")
        assert not DNSFailureHandler.is_open("example.com")

    def test_failure_threshold_reached(self):
        for _ in range(3):
            DNSFailureHandler.record_failure("example.com")
        assert DNSFailureHandler.is_open("example.com")

    def test_success_resets_counter(self):
        DNSFailureHandler.record_failure("x.com")
        DNSFailureHandler.record_failure("x.com")
        DNSFailureHandler.record_success("x.com")
        assert not DNSFailureHandler.is_open("x.com")

    def test_reset_single(self):
        for _ in range(3):
            DNSFailureHandler.record_failure("alpha.com")
        DNSFailureHandler.record_failure("beta.com")
        DNSFailureHandler.record_failure("beta.com")
        assert DNSFailureHandler.is_open("alpha.com")
        assert not DNSFailureHandler.is_open("beta.com")
        DNSFailureHandler.reset("alpha.com")
        assert not DNSFailureHandler.is_open("alpha.com")

    def test_reset_all(self):
        for _ in range(3):
            DNSFailureHandler.record_failure("a.com")
            DNSFailureHandler.record_failure("b.com")
        assert DNSFailureHandler.is_open("a.com")
        assert DNSFailureHandler.is_open("b.com")
        DNSFailureHandler.reset()
        assert not DNSFailureHandler.is_open("a.com")
        assert not DNSFailureHandler.is_open("b.com")

    def test_per_hostname_isolation(self):
        for _ in range(3):
            DNSFailureHandler.record_failure("bad.com")
        assert DNSFailureHandler.is_open("bad.com")
        assert not DNSFailureHandler.is_open("good.com")


class TestOrchestratorClientDNS:
    def setup_method(self):
        DNSFailureHandler.reset()
        self.client = OrchestratorClient(base_url="https://api.test-orchestrator.io", api_key="test-key-123")

    def test_dns_failure_returns_error_not_crash(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror):
            result = self.client._request("GET", "/agents")
        assert result.get("error") == "dns_failure"

    def test_http_error_not_treated_as_dns(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"error": "not_found"}'
        mock_resp.__enter__.return_value = mock_resp
        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            with patch("src.sdk.client._resolve_hostname", return_value="api.test-orchestrator.io"):
                result = self.client._request("GET", "/agents/nonexistent")
        assert result.get("error") != "dns_failure"

    def test_circuit_breaker_short_circuits(self):
        DNSFailureHandler._failures["api.test-orchestrator.io"] = 3
        DNSFailureHandler._circuit_open_until["api.test-orchestrator.io"] = 9999999999.0
        with patch("src.sdk.client.urlopen") as mock:
            result = self.client._request("GET", "/agents")
            assert result.get("error") == "dns_circuit_open"
            mock.assert_not_called()
