"""Tests for SDK client module."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sdk.client import OrchestratorClient


def test_reject_empty_name():
    client = OrchestratorClient(base_url="http://test", api_key="test")
    raised = False
    try:
        client.register_agent("", "worker")
    except ValueError:
        raised = True
    assert raised


def test_reject_whitespace_name():
    client = OrchestratorClient(base_url="http://test", api_key="test")
    raised = False
    try:
        client.register_agent("   ", "worker")
    except ValueError:
        raised = True
    assert raised


def test_reject_none_name():
    client = OrchestratorClient(base_url="http://test", api_key="test")
    raised = False
    try:
        client.register_agent(None, "worker")
    except ValueError:
        raised = True
    assert raised


def test_valid_name_passes():
    client = OrchestratorClient(base_url="http://test", api_key="test")
    result = client.register_agent("my-agent", "worker")
    assert result is not None
