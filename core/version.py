import os
import subprocess
from functools import lru_cache

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@lru_cache(maxsize=1)
def _describe_version():
    """Runs `git describe --tags --dirty` and returns the tag with any leading
    'v' stripped, or None if git is unavailable, the command fails, or times out."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--dirty"],
            cwd=_BASE_DIR,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None

    version = result.stdout.strip()
    if version.startswith("v"):
        version = version[1:]
    return version


def get_version() -> str:
    """Returns the app version: the APP_VERSION env var if set and non-empty
    (this is how container builds ship a version baked in at build time);
    otherwise derives it from `git describe --tags --dirty` for local dev
    runs, appending '+dev', or falls back to '0.0.0+dev' if git is
    unavailable."""
    env_version = os.getenv("APP_VERSION")
    if env_version:
        return env_version

    described = _describe_version()
    if described is None:
        return "0.0.0+dev"
    return f"{described}+dev"
