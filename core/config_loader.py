import os
import yaml
import logging

logger = logging.getLogger("quadlet-manager.config")

class AppConfig:
    def __init__(self):
        self.master_key = os.getenv("QUADLET_MASTER_KEY", "")
        self.session_timeout = 3600
        self.poll_frequency = 10
        self._load_from_yaml()

    def _load_from_yaml(self):
        config_path = os.getenv("QUADLET_CONFIG_PATH", "config.yaml")
        if not os.path.exists(config_path):
            logger.info(f"Config file not found at {config_path}. Using environment defaults.")
            return

        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
                
            # Override defaults if specified in yaml
            if "master_key" in data:
                self.master_key = data["master_key"]
            if "session_timeout" in data:
                self.session_timeout = int(data["session_timeout"])
            if "poll_frequency" in data:
                self.poll_frequency = int(data["poll_frequency"])
                
            logger.info("Loaded configuration from config.yaml.")
                
        except Exception as e:
            logger.error(f"Failed to load {config_path}: {e}")

global_config = AppConfig()
