import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VERSION_FILE = os.path.join(_BASE_DIR, "VERSION")


def get_version() -> str:
    """Returns the app version: APP_VERSION env var if set, else VERSION file + '+dev'."""
    env_version = os.getenv("APP_VERSION")
    if env_version:
        return env_version

    with open(_VERSION_FILE, "r") as f:
        base_version = f.read().strip()

    return f"{base_version}+dev"
