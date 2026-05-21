"""Tests for coerce boolean env values in Config._load_env_overrides."""
import os
import json
import pytest
from src.common.config import Config


class TestConfigCoerceValue:
    """Test the _coerce_value static method directly."""

    def test_coerce_true_strings(self):
        true_values = ["true", "True", "TRUE", "1", "yes", "Yes", "YES", "y", "Y", "on", "ON", "  true  "]
        for v in true_values:
            assert Config._coerce_value(v) is True, f"'{v}' should be True"

    def test_coerce_false_strings(self):
        false_values = ["false", "False", "FALSE", "0", "no", "No", "NO", "n", "N", "off", "OFF"]
        for v in false_values:
            assert Config._coerce_value(v) is False, f"'{v}' should be False"

    def test_coerce_integer(self):
        assert Config._coerce_value("42") == 42
        assert Config._coerce_value("0") == 0
        assert Config._coerce_value("-1") == -1

    def test_coerce_float(self):
        assert Config._coerce_value("3.14") == 3.14

    def test_coerce_keeps_string(self):
        assert Config._coerce_value("some_string") == "some_string"
        assert Config._coerce_value("hello") == "hello"
        assert Config._coerce_value("") == ""

    def test_coerce_env_override_boolean(self, monkeypatch):
        monkeypatch.setenv("AO_FEATURE_ENABLED", "false")
        config = Config()
        assert config.get("feature.enabled") is False
        assert config.get("feature.enabled") is not True

    def test_coerce_env_override_boolean_true(self, monkeypatch):
        monkeypatch.setenv("AO_FEATURE_ENABLED", "true")
        config = Config()
        assert config.get("feature.enabled") is True

    def test_coerce_env_override_integer(self, monkeypatch):
        monkeypatch.setenv("AO_DATABASE_PORT", "5432")
        config = Config()
        assert config.get("database.port") == 5432
        assert isinstance(config.get("database.port"), int)

    def test_coerce_env_override_yes_no(self, monkeypatch):
        monkeypatch.setenv("AO_LOGGING_VERBOSE", "yes")
        config = Config()
        assert config.get("logging.verbose") is True

    def test_coerce_env_override_off(self, monkeypatch):
        monkeypatch.setenv("AO_CACHE_ENABLED", "off")
        config = Config()
        assert config.get("cache.enabled") is False

    def test_coerce_env_override_keeps_string(self, monkeypatch):
        monkeypatch.setenv("AO_APP_NAME", "myapp")
        config = Config()
        assert config.get("app.name") == "myapp"

    def test_coerce_env_override_with_underscores(self, monkeypatch):
        monkeypatch.setenv("AO_DB_POOL_SIZE", "10")
        config = Config()
        assert config.get("db.pool.size") == 10
        assert isinstance(config.get("db.pool.size"), int)

    def test_existing_tests_still_pass(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"app": {"name": "test", "port": 8080}}')
        config = Config(str(config_file))
        assert config.get("app.name") == "test"
        assert config.get("app.port") == 8080

        config2 = Config()
        assert config2.get("nonexistent.key", "default") == "default"

        config3 = Config()
        config3.set("database.host", "localhost")
        assert config3.get("database.host") == "localhost"

        config4 = Config()
        config4.set("a.b.c.d", "value")
        assert config4.get("a.b.c.d") == "value"
