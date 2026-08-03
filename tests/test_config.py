import pytest
import os
import unittest
import yaml
import tempfile
from unittest.mock import patch

class TestConfigLoader(unittest.TestCase):
    def setUp(self):
        # Snapshot the original environment so tearDown can restore it exactly,
        # rather than deleting variables that may have been set by the caller.
        self._original_env = {
            key: os.environ.get(key)
            for key in ("QUADLET_CONFIG_PATH", "QUADLET_MASTER_KEY", "DEV_AUTO_LOGIN")
        }

        # Create a temporary config.yaml
        self.test_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.test_dir.name, "test_config.yaml")

        test_data = {
            "master_key": "yaml_secret_key",
            "poll_frequency": 25,
            "session_timeout": 7200,
            "dev_auto_login": True
        }

        with open(self.config_path, "w") as f:
            yaml.dump(test_data, f)

        os.environ["QUADLET_CONFIG_PATH"] = self.config_path

    @pytest.mark.unit
    def test_yaml_override(self):
        # We import here so it evaluates the environment variables freshly
        from core.config_loader import AppConfig
        
        config = AppConfig()
        
        self.assertEqual(config.master_key, "yaml_secret_key")
        self.assertEqual(config.poll_frequency, 25)
        self.assertEqual(config.session_timeout, 7200)
        self.assertTrue(config.dev_auto_login)

    @pytest.mark.unit
    def test_missing_config_fallback(self):
        with patch.dict(os.environ, {
            "QUADLET_CONFIG_PATH": "/nonexistent/config.yaml",
            "QUADLET_MASTER_KEY": "env_fallback_key",
        }):
            from core.config_loader import AppConfig
            config = AppConfig()

            self.assertEqual(config.master_key, "env_fallback_key")
            self.assertEqual(config.poll_frequency, 10)  # Default
            # Default dev_auto_login follows DEV_AUTO_LOGIN env
            self.assertFalse(config.dev_auto_login)

    @pytest.mark.unit
    def test_malformed_yaml_falls_back_to_env_defaults(self):
        # Overwrite the config file with invalid YAML
        with open(self.config_path, "w") as f:
            f.write("master_key: [unclosed\n\t bad: indent")

        with patch.dict(os.environ, {"QUADLET_MASTER_KEY": "env_fallback_key"}):
            from core.config_loader import AppConfig
            with self.assertLogs("quadlet-manager.config", level="ERROR") as logs:
                config = AppConfig()

            self.assertEqual(config.master_key, "env_fallback_key")
            self.assertEqual(config.poll_frequency, 10)  # Default
            self.assertEqual(config.session_timeout, 3600)  # Default
            self.assertTrue(any("Failed to load" in msg for msg in logs.output))

    @pytest.mark.unit
    def test_invalid_value_type_falls_back_to_env_defaults(self):
        # Valid YAML but a value that fails int() conversion
        with open(self.config_path, "w") as f:
            yaml.dump({"session_timeout": "not-a-number"}, f)

        from core.config_loader import AppConfig
        with self.assertLogs("quadlet-manager.config", level="ERROR") as logs:
            config = AppConfig()

        self.assertEqual(config.session_timeout, 3600)  # Default
        self.assertTrue(any("Failed to load" in msg for msg in logs.output))

    def tearDown(self):
        self.test_dir.cleanup()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

if __name__ == "__main__":
    unittest.main()
