import pytest
from src.common.config import Config


class TestConfig:
    def test_load_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"app": {"name": "test", "port": 8080}}')
        config = Config(str(config_file))
        assert config.get("app.name") == "test"
        assert config.get("app.port") == 8080

    def test_load_rejects_array_root(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('["not", "an", "object"]')
        config = Config()
        with pytest.raises(ValueError, match="Config root must be a JSON object"):
            config.load(str(config_file))
        assert config.to_dict() == {}

    def test_load_rejects_scalar_root(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('"just a string"')
        config = Config()
        with pytest.raises(ValueError, match="Config root must be a JSON object"):
            config.load(str(config_file))
        assert config.to_dict() == {}

    def test_load_rejects_number_root(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('42')
        config = Config()
        with pytest.raises(ValueError, match="Config root must be a JSON object"):
            config.load(str(config_file))
        assert config.to_dict() == {}

    def test_load_preserves_existing_state_on_rejection(self, tmp_path):
        config = Config()
        config.set("existing.key", "value")
        config_file = tmp_path / "config.json"
        config_file.write_text('["bad", "root"]')
        with pytest.raises(ValueError, match="Config root must be a JSON object"):
            config.load(str(config_file))
        assert config.get("existing.key") == "value"

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

