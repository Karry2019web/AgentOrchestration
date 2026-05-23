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

    def test_to_redacted_dict_masks_api_key(self):
        config = Config()
        config.set("api_key", "sk-12345-secret")
        redacted = config.to_redacted_dict()
        assert redacted["api_key"] == "****"

    def test_to_redacted_dict_masks_nested_secret(self):
        config = Config()
        config.set("database.password", "supersecret")
        redacted = config.to_redacted_dict()
        assert redacted["database"]["password"] == "****"

    def test_to_redacted_dict_keeps_plain_values(self):
        config = Config()
        config.set("app.name", "test-app")
        config.set("app.port", 8080)
        config.set("logging.level", "info")
        redacted = config.to_redacted_dict()
        assert redacted["app"]["name"] == "test-app"
        assert redacted["app"]["port"] == 8080
        assert redacted["logging"]["level"] == "info"

    def test_to_redacted_dict_mixed_config(self):
        config = Config()
        config.set("api_key", "sk-123")
        config.set("host", "localhost")
        config.set("db.password", "p@ss")
        config.set("db.user", "admin")
        redacted = config.to_redacted_dict()
        assert redacted["api_key"] == "****"
        assert redacted["host"] == "localhost"
        assert redacted["db"]["password"] == "****"
        assert redacted["db"]["user"] == "admin"

    def test_to_redacted_dict_preserves_to_dict(self):
        """to_dict still returns full plain-text config."""
        config = Config()
        config.set("api_key", "sk-123")
        plain = config.to_dict()
        assert plain["api_key"] == "sk-123"
