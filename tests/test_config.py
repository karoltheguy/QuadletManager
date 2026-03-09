import os
import unittest
import yaml
import tempfile
from unittest.mock import patch

class TestConfigLoader(unittest.TestCase):
    def setUp(self):
        # Create a temporary config.yaml
        self.test_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.test_dir.name, "test_config.yaml")
        
        test_data = {
            "master_key": "yaml_secret_key",
            "poll_frequency": 25,
            "session_timeout": 7200
        }
        
        with open(self.config_path, "w") as f:
            yaml.dump(test_data, f)
            
        os.environ["QUADLET_CONFIG_PATH"] = self.config_path

    def test_yaml_override(self):
        # We import here so it evaluates the environment variables freshly
        from config_loader import AppConfig
        
        config = AppConfig()
        
        self.assertEqual(config.master_key, "yaml_secret_key")
        self.assertEqual(config.poll_frequency, 25)
        self.assertEqual(config.session_timeout, 7200)

    def test_missing_config_fallback(self):
        os.environ["QUADLET_CONFIG_PATH"] = "/nonexistent/config.yaml"
        os.environ["QUADLET_MASTER_KEY"] = "env_fallback_key"
        
        from config_loader import AppConfig
        config = AppConfig()
        
        self.assertEqual(config.master_key, "env_fallback_key")
        self.assertEqual(config.poll_frequency, 10)  # Default

    def tearDown(self):
        self.test_dir.cleanup()
        if "QUADLET_CONFIG_PATH" in os.environ:
            del os.environ["QUADLET_CONFIG_PATH"]
        if "QUADLET_MASTER_KEY" in os.environ:
            del os.environ["QUADLET_MASTER_KEY"]

if __name__ == "__main__":
    unittest.main()
