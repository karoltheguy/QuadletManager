import os
import yaml
import logging

logger = logging.getLogger("quadlet-manager.config")

class AppConfig:
    def __init__(self):
        """Initialize AppConfig with default values."""
        self.master_key = os.getenv("QUADLET_MASTER_KEY", "")
        self.session_timeout = 3600
        self.poll_frequency = 10
        # When True, backend skips login and treats all users as 'editor'.
        # Defaults from DEV_AUTO_LOGIN env, but can be overridden in config.yaml.
        self.dev_auto_login = os.getenv("DEV_AUTO_LOGIN") == "1"
        # When True, connect_to_server() refuses to connect to a server whose
        # host key has not yet been pinned instead of silently trusting it.
        self.ssh_strict_host_keys = False
        # When True, the session cookie always carries the Secure flag, so the
        # browser will only ever send it back over HTTPS. It defaults to False
        # because the shipped compose file serves plain HTTP on :8000, where a
        # Secure cookie would be dropped and login would silently never stick.
        # Requests that already arrive over HTTPS get the flag regardless; this
        # setting is for deployments terminating TLS at a proxy that does not
        # forward X-Forwarded-Proto.
        self.secure_cookies = os.getenv("QUADLET_SECURE_COOKIES") == "1"
        self._load_from_yaml()

    def _apply_config_data(self, data):
        """Override defaults if specified in yaml."""
        if "master_key" in data:
            self.master_key = data["master_key"]
        if "session_timeout" in data:
            self.session_timeout = int(data["session_timeout"])
        if "poll_frequency" in data:
            self.poll_frequency = int(data["poll_frequency"])
        if "dev_auto_login" in data:
            # Accept booleans or 0/1 style ints in YAML
            value = data["dev_auto_login"]
            if isinstance(value, bool):
                self.dev_auto_login = value
            else:
                self.dev_auto_login = str(value) == "1"
        if "ssh_strict_host_keys" in data:
            # Accept booleans or 0/1 style ints in YAML
            value = data["ssh_strict_host_keys"]
            if isinstance(value, bool):
                self.ssh_strict_host_keys = value
            else:
                self.ssh_strict_host_keys = str(value) == "1"
        if "secure_cookies" in data:
            # Accept booleans or 0/1 style ints in YAML
            value = data["secure_cookies"]
            if isinstance(value, bool):
                self.secure_cookies = value
            else:
                self.secure_cookies = str(value) == "1"

    def _load_from_yaml(self):
        config_path = os.getenv("QUADLET_CONFIG_PATH", "config.yaml")
        if not os.path.exists(config_path):
            logger.info(f"Config file not found at {config_path}. Using environment defaults.")
            return

        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}

            self._apply_config_data(data)

            logger.info(f"Loaded configuration from {config_path}.")

        except (OSError, yaml.YAMLError, ValueError, TypeError):
            # Expected failures (missing/unreadable file, malformed YAML, bad
            # value types): log and fall back to environment defaults.
            # Anything else is unexpected and must not be silently swallowed.
            logger.exception(f"Failed to load {config_path}. Falling back to environment defaults.")

global_config = AppConfig()
