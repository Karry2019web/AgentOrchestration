import pytest
import os
from src.common.config import Config, _coerce_value


class TestCoerceValue:
    def test_coerce_int(self):
        assert _coerce_value("42") == 42
        assert _coerce_value("0") == 0
        assert _coerce_value("-1") == -1

    def test_coerce_float(self):
        assert _coerce_value("3.14") == 3.14
        assert _coerce_value("-0.5") == -0.5
        assert _coerce_value(".5") == 0.5

    def test_coerce_string(self):
        assert _coerce_value("hello") == "hello"
        assert _coerce_value("8080a") == "8080a"
        assert _coerce_value("") == ""

    def test_coerce_whitespace(self):
        assert _coerce_value("  42  ") == 42
        assert _coerce_value("  hello  ") == "  hello  "

    def test_coerce_scientific(self):
        assert _coerce_value("1e3") == 1000.0
        assert _coerce_value("1.5e2") == 150.0


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

    def test_env_override_int(self, monkeypatch):
        monkeypatch.setenv("AO_APP_PORT", "8080")
        config = Config()
        value = config.get("app.port")
        assert value == 8080
        assert isinstance(value, int)

    def test_env_override_float(self, monkeypatch):
        monkeypatch.setenv("AO_TIMEOUT_SECONDS", "30.5")
        config = Config()
        value = config.get("timeout.seconds")
        assert value == 30.5
        assert isinstance(value, float)

    def test_env_override_string(self, monkeypatch):
        monkeypatch.setenv("AO_APP_NAME", "myapp")
        config = Config()
        value = config.get("app.name")
        assert value == "myapp"
        assert isinstance(value, str)

    def test_env_override_negative_int(self, monkeypatch):
        monkeypatch.setenv("AO_OFFSET", "-5")
        config = Config()
        value = config.get("offset")
        assert value == -5
        assert isinstance(value, int)
