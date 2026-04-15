import socket
import pytest


def _server_is_up(host: str = "localhost", port: int = 8000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(items):
    """Skip Playwright (page-fixture) tests when the app server is not reachable."""
    if _server_is_up():
        return

    skip = pytest.mark.skip(reason="Live server not running on localhost:8000")
    for item in items:
        if "page" in getattr(item, "fixturenames", []):
            item.add_marker(skip)
