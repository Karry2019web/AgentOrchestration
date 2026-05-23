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

    def test_coerce_int(self, monkeypatch):
        monkeypatch.setenv("AO_APP_PORT", "8080")
        config = Config()
        assert config.get("app.port") == 8080
        assert isinstance(config.get("app.port"), int)

    def test_coerce_float(self, monkeypatch):
        monkeypatch.setenv("AO_RATE_LIMIT", "3.14")
        config = Config()
        assert config.get("rate.limit") == 3.14
        assert isinstance(config.get("rate.limit"), float)

    def test_coerce_negative_int(self, monkeypatch):
        monkeypatch.setenv("AO_LOG_LEVEL", "-1")
        config = Config()
        assert config.get("log.level") == -1
        assert isinstance(config.get("log.level"), int)

    def test_coerce_string_unchanged(self, monkeypatch):
        monkeypatch.setenv("AO_APP_NAME", "myapp")
        config = Config()
        assert config.get("app.name") == "myapp"
        assert isinstance(config.get("app.name"), str)

    def test_coerce_mixed_string(self, monkeypatch):
        monkeypatch.setenv("AO_HOST_ADDR", "localhost")
        config = Config()
        assert config.get("host.addr") == "localhost"
        assert isinstance(config.get("host.addr"), str)

    def test_coerce_float_like_int(self, monkeypatch):
        monkeypatch.setenv("AO_TIMEOUT_SECS", "30.0")
        config = Config()
        assert config.get("timeout.secs") == 30.0
        assert isinstance(config.get("timeout.secs"), float)
