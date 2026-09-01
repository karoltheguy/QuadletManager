import asyncio
import os
import shutil
import socket
from urllib.parse import urlparse

import pytest

from tests.app_url import app_base_url as _app_base_url


@pytest.fixture(scope="session")
def _database_template(tmp_path_factory):
    """Build an initialized database once per worker.

    Tests copy this rather than each running init_db(), which at ~800 tests
    would dominate the suite's runtime. Session scope means one per xdist
    worker process, since each worker imports its own copy of the module.
    """
    from core import database as db_module

    template = tmp_path_factory.mktemp("db-template") / "quadlets.db"
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = str(template)
    try:
        asyncio.run(db_module.init_db())
    finally:
        db_module.DATABASE_PATH = original
    return template


@pytest.fixture(autouse=True)
def isolated_database(_database_template, tmp_path, monkeypatch):
    """Give every test its own SQLite file.

    core/database.py binds DATABASE_PATH once, at import time, so a test that
    only sets the QUADLET_DB_PATH environment variable silently keeps using the
    repo-root quadlets.db -- the module attribute was already resolved before
    the fixture ran. Under `-n auto` that means every xdist worker writes the
    same file, which shows up as `sqlite3.OperationalError: database is locked`
    and as assertions tripping over rows another worker's init_db() seeded.

    Assigning the module attribute is the form that actually takes effect, and
    is what most of the suite already does by hand. Doing it here covers the
    tests that never isolated the database at all -- notably the ones that build
    a TestClient(app), whose startup runs init_db() for them.

    The env var is set too so that anything reading it at runtime agrees with
    the module attribute rather than pointing at a second, different file.

    The copied template carries the schema, which is what the shared file used
    to provide incidentally -- several tests exercise code that writes to tables
    they never create themselves.
    """
    from core import database as db_module

    db_path = tmp_path / "quadlets.db"
    shutil.copyfile(_database_template, db_path)
    monkeypatch.setattr(db_module, "DATABASE_PATH", str(db_path))
    monkeypatch.setenv("QUADLET_DB_PATH", str(db_path))
    return db_path


@pytest.fixture(autouse=True)
def isolated_background_loops(monkeypatch):
    """Keep the app's background tasks from doing real work during tests.

    The lifespan starts three background tasks: polling_engine_loop,
    stats_engine_loop, and container_events_cleanup_loop. polling_engine_loop
    runs a reconcile plus check_quadlets cycle before its first sleep
    (services/sync_engine.py:349-357), so it issues real SSH through the same
    `pool` singleton tests patch. Neutralizing all three here keeps individual
    tests from having to know they exist.
    """
    import main

    async def _noop():
        return

    monkeypatch.setattr(main, "polling_engine_loop", _noop)
    monkeypatch.setattr(main, "stats_engine_loop", _noop)
    monkeypatch.setattr(main, "container_events_cleanup_loop", _noop)


def _server_is_up(url: str | None = None) -> bool:
    parsed = urlparse(url or _app_base_url())
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname or "localhost", port), timeout=1):
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

    base_url = _app_base_url()
    if _server_is_up(base_url):
        return

    skip = pytest.mark.skip(reason=f"Live server not running on {base_url}")
    for item in items:
        if "page" in getattr(item, "fixturenames", []):
            item.add_marker(skip)

# Must stay identical to the `unmarked` suite's marker in
# .github/workflows/tests.yml, in both matrix blocks. The two are matched by
# string equality below, so a change to one without the other silently stops
# the exit-5 conversion and the job goes red on an empty collection.
UNMARKED_MARKEXPR = "not unit and not integration and not e2e and not podman"


def pytest_sessionfinish(session, exitstatus):
    """
    Return exit code 0 if pytest exits with code 5 (no tests collected) on condition.
    This prevents CI from failing when the `unmarked` suite's marker matches 0 tests.
    """
    if exitstatus == 5:
        markexpr = getattr(session.config.option, "markexpr", "")
        if markexpr == UNMARKED_MARKEXPR:
            session.exitstatus = 0
