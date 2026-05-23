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

    # --- Resource limit validation tests ---

    def test_validate_resource_limits_valid(self):
        """Valid positive integers should not raise."""
        Config.validate_resource_limits(60, 512, 100)

    def test_validate_resource_limits_negative_cpu(self):
        """Negative cpu_time should raise ValueError."""
        with pytest.raises(ValueError, match="cpu_time"):
            Config.validate_resource_limits(-1, 512, 100)

    def test_validate_resource_limits_zero_cpu(self):
        """Zero cpu_time should raise ValueError."""
        with pytest.raises(ValueError, match="cpu_time"):
            Config.validate_resource_limits(0, 512, 100)

    def test_validate_resource_limits_negative_memory(self):
        """Negative memory_mb should raise ValueError."""
        with pytest.raises(ValueError, match="memory_mb"):
            Config.validate_resource_limits(60, -1, 100)

    def test_validate_resource_limits_negative_disk(self):
        """Negative disk_mb should raise ValueError."""
        with pytest.raises(ValueError, match="disk_mb"):
            Config.validate_resource_limits(60, 512, -1)

    def test_validate_resource_limits_non_int(self):
        """Non-integer values should raise ValueError."""
        with pytest.raises(ValueError, match="cpu_time"):
            Config.validate_resource_limits("60", 512, 100)
