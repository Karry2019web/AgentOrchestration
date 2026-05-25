import pytest
from src.common.config import Config


class TestConfig:
    def test_load_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"app": {"name": "test", "port": 8080}}')
        config = Config(str(config_file))
        assert config.get("app.name") == "test"
        assert config.get("app.port") == 8080

    def test_default_value(self):
        config = Config()
        assert config.get("nonexistent.key", "default") == "default"

    def test_set_value(self):
        config = Config()
        config.set("database.host", "localhost")
        assert config.get("database.host") == "localhost"

    def test_nested_set(self):
        config = Config()
        config.set("a.b.c.d", "value")
        assert config.get("a.b.c.d") == "value"

    def test_to_dict(self):
        config = Config()
        config.set("key1", "value1")
        config.set("key2", "value2")
        data = config.to_dict()
        assert data["key1"] == "value1"
        assert data["key2"] == "value2"

    def test_env_override_allowlist(self, monkeypatch):
        """Only documented AO_ variables should be imported."""
        monkeypatch.setenv("AO_DB_HOST", "allowed-host")
        monkeypatch.setenv("AO_AGENT_ID", "should-not-leak")
        config = Config()
        assert config.get("db.host") == "allowed-host"
        assert config.get("agent.id") is None

    def test_env_override_allowlist_unknown_skipped(self, monkeypatch):
        """Undocumented AO_ variables must NOT appear in config."""
        monkeypatch.setenv("AO_SECRET_TOKEN", "leaked-token")
        config = Config()
        data = config.to_dict()
        assert "secret" not in data
        assert "secret.token" not in str(data)
