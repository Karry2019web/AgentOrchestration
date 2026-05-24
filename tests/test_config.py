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


class TestConfigGetBool:
    def test_bool_true_strings(self):
        config = Config()
        config.set("flag", "true")
        assert config.get_bool("flag") is True
        config.set("flag", "1")
        assert config.get_bool("flag") is True
        config.set("flag", "yes")
        assert config.get_bool("flag") is True
        config.set("flag", "on")
        assert config.get_bool("flag") is True
        config.set("flag", "TRUE")
        assert config.get_bool("flag") is True

    def test_bool_false_strings(self):
        config = Config()
        config.set("flag", "false")
        assert config.get_bool("flag") is False
        config.set("flag", "0")
        assert config.get_bool("flag") is False
        config.set("flag", "no")
        assert config.get_bool("flag") is False
        config.set("flag", "off")
        assert config.get_bool("flag") is False
        config.set("flag", "FALSE")
        assert config.get_bool("flag") is False

    def test_bool_native_types(self):
        config = Config()
        config.set("flag", True)
        assert config.get_bool("flag") is True
        config.set("flag", False)
        assert config.get_bool("flag") is False
        config.set("flag", 1)
        assert config.get_bool("flag") is True
        config.set("flag", 0)
        assert config.get_bool("flag") is False

    def test_bool_default(self):
        config = Config()
        assert config.get_bool("nonexistent") is False
        assert config.get_bool("nonexistent", True) is True

    def test_bool_unsupported_string_raises(self):
        config = Config()
        config.set("flag", "maybe")
        with pytest.raises(ValueError, match="Cannot coerce string"):
            config.get_bool("flag")

    def test_bool_none_value_with_default(self):
        config = Config()
        config.set("flag", None)
        assert config.get_bool("flag", True) is True
        assert config.get_bool("flag", False) is False
