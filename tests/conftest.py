import socket
import pytest


def _server_is_up(host: str = "localhost", port: int = 8000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    """Skip Playwright (page-fixture) tests when the app server is not reachable,
    and skip the local-only code quality checks unless targeted explicitly."""
    if not any("test_code_quality" in arg for arg in config.args):
        skip_quality = pytest.mark.skip(
            reason="Local-only check; run with: pytest tests/test_code_quality.py"
        )
        for item in items:
            if item.fspath.basename == "test_code_quality.py":
                item.add_marker(skip_quality)

    if _server_is_up():
        return

    skip = pytest.mark.skip(reason="Live server not running on localhost:8000")
    for item in items:
        if "page" in getattr(item, "fixturenames", []):
            item.add_marker(skip)

def pytest_sessionfinish(session, exitstatus):
    """
    Return exit code 0 if pytest exits with code 5 (no tests collected) on condition.
    This prevents CI from failing when marker "not unit and not integration and not e2e" matches 0 tests.
    """
    if exitstatus == 5:
        markexpr = getattr(session.config.option, "markexpr", "")
        if markexpr == "not unit and not integration and not e2e":
            session.exitstatus = 0
