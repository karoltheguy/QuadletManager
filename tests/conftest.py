import asyncio
import shutil
import socket
import pytest


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
