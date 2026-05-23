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

    def test_set_isolates_nested_dict(self):
        nested = {"inner": "original"}
        config = Config()
        config.set("nested", nested)
        nested["inner"] = "mutated"
        assert config.get("nested.inner") == "original"

    def test_to_dict_isolates_internal_state(self):
        config = Config()
        config.set("nested", {"inner": "value"})
        data = config.to_dict()
        data["nested"]["inner"] = "mutated"
        assert config.get("nested.inner") == "value"

    def test_load_isolates_nested_state(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"app": {"name": "original"}}')
        config = Config(str(config_file))
        data = config.to_dict()
        data["app"]["name"] = "mutated"
        assert config.get("app.name") == "original"
