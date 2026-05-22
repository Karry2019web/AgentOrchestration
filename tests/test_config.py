import pytest
from src.common.config import Config, ConfigError


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

    def test_malformed_json_raises_config_error(self, tmp_path):
        config_file = tmp_path / "bad.json"
        config_file.write_text('{"app": {"name": "test", port: 8080}}')  # missing quotes around port
        with pytest.raises(ConfigError) as excinfo:
            Config(str(config_file))
        assert str(config_file) in str(excinfo.value)
        assert "line" in str(excinfo.value).lower() or "column" in str(excinfo.value).lower()

    def test_missing_file_raises_config_error(self):
        with pytest.raises(ConfigError) as excinfo:
            Config("/nonexistent/path/config.json")
        assert "not found" in str(excinfo.value).lower()
