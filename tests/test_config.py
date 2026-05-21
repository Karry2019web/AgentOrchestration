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

    def test_rejects_oversized_config_file(self, tmp_path):
        """Should reject config files exceeding MAX_CONFIG_SIZE."""
        from src.common.config import MAX_CONFIG_SIZE

        # Create a file just over the limit
        large_file = tmp_path / "too_large.json"
        size = MAX_CONFIG_SIZE + 1
        with open(large_file, "wb") as f:
            f.write(b" " * size)

        with pytest.raises(ConfigError, match="too large|Config file too large"):
            Config(str(large_file))

    def test_accepts_normal_sized_config(self, tmp_path):
        """Should accept config files under MAX_CONFIG_SIZE."""
        config_file = tmp_path / "normal.json"
        config_file.write_text('{"key": "value"}')
        config = Config(str(config_file))
        assert config.get("key") == "value"
