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

    def test_coerce_env_true_to_boolean(self, monkeypatch):
        monkeypatch.setenv("AO_FEATURE_ENABLED", "true")
        config = Config()
        assert config.get("feature.enabled") is True
        assert isinstance(config.get("feature.enabled"), bool)

    def test_coerce_env_false_to_boolean(self, monkeypatch):
        monkeypatch.setenv("AO_FEATURE_ENABLED", "false")
        config = Config()
        assert config.get("feature.enabled") is False
        assert isinstance(config.get("feature.enabled"), bool)

    def test_coerce_env_mixed_case(self, monkeypatch):
        monkeypatch.setenv("AO_FLAG", "True")
        config = Config()
        assert config.get("flag") is True

    def test_coerce_env_non_boolean_preserved(self, monkeypatch):
        monkeypatch.setenv("AO_DB_HOST", "localhost")
        config = Config()
        assert config.get("db.host") == "localhost"
        assert not isinstance(config.get("db.host"), bool)

    def test_coerce_env_numeric_preserved(self, monkeypatch):
        monkeypatch.setenv("AO_PORT", "8080")
        config = Config()
        # Numeric strings stay as strings (not coerced to int)
        assert config.get("port") == "8080"

    def test_boolean_env_overrides_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AO_APP_NAME", "false")
        config_file = tmp_path / "config.json"
        config_file.write_text('{"app": {"name": "test", "port": 8080}}')
        config = Config(str(config_file))
        # Config file has "test", env override sets it to False
        assert config.get("app.name") is False

    def test_coerce_value_static(self):
        assert Config._coerce_value("true") is True
        assert Config._coerce_value("false") is False
        assert Config._coerce_value("True") is True
        assert Config._coerce_value("FALSE") is False
        assert Config._coerce_value("  true  ") is True
        assert Config._coerce_value("localhost") == "localhost"
        assert Config._coerce_value("8080") == "8080"
        assert Config._coerce_value("") == ""
