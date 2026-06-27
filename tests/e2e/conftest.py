"""Package-scoped Playwright fixtures.

pytest-playwright declares playwright/browser_type/launch_browser/browser at
session scope by default.  That means Playwright's internal event loop stays
alive for the whole test session, and its sync API leaves asyncio._running_loop
set after every call.  When pytest-asyncio then tries to create a Runner for
the first async test, it sees a "running" loop and crashes.

By re-declaring the full fixture chain here at package scope, Playwright's
event loop is created and properly torn down (pw.stop() → loop.run_until_complete
→ asyncio._set_running_loop(None)) before any async tests in the parent package
run.  The async tests therefore start with a clean asyncio state.

Reference: https://github.com/microsoft/playwright-pytest/issues/289
"""
import os
import sqlite3
import json
import tempfile
import pytest
from typing import Any, Callable, Dict, Generator, Optional
from playwright.sync_api import Browser, BrowserType, Playwright, sync_playwright

@pytest.fixture(scope="package", autouse=True)
def seed_e2e_database_if_empty():
    """Ensure the backend database has at least one server for E2E tests."""
    db_path = os.environ.get("QUADLET_DB_PATH", "quadlets.db")
    if not os.path.exists(db_path):
        return
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM servers")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO servers (name, ip_address, ssh_user) VALUES (?, ?, ?)",
                ("Mock Server", "localhost", "root")
            )
            conn.commit()
    except Exception:
        pass
    finally:
        if 'conn' in locals():
            conn.close()



@pytest.fixture(scope="package")
def _pw_artifacts_folder() -> Generator[tempfile.TemporaryDirectory, None, None]:
    artifacts_folder = tempfile.TemporaryDirectory(prefix="playwright-pytest-")
    yield artifacts_folder
    try:
        artifacts_folder.cleanup()
    except (PermissionError, NotADirectoryError):
        pass


@pytest.fixture(scope="package")
def playwright() -> Generator[Playwright, None, None]:
    pw = sync_playwright().start()
    yield pw
    pw.stop()


@pytest.fixture(scope="package")
def browser_type(playwright: Playwright, browser_name: str) -> BrowserType:
    return getattr(playwright, browser_name)


@pytest.fixture(scope="package")
def browser_context_args(
    pytestconfig: Any,
    playwright: Playwright,
    device: Optional[str],
    base_url: Optional[str],
    _pw_artifacts_folder: tempfile.TemporaryDirectory,
) -> Dict:
    context_args: Dict = {}
    if device:
        context_args.update(playwright.devices[device])
    if base_url:
        context_args["base_url"] = base_url

    video_option = pytestconfig.getoption("--video")
    capture_video = video_option in ["on", "retain-on-failure"]
    if capture_video:
        context_args["record_video_dir"] = _pw_artifacts_folder.name

    return context_args


@pytest.fixture(scope="package")
def launch_browser(
    browser_type_launch_args: Dict,
    browser_type: BrowserType,
    connect_options: Optional[Dict],
) -> Callable[..., Browser]:
    def launch(**kwargs: Dict) -> Browser:
        launch_options = {**browser_type_launch_args, **kwargs}
        if connect_options:
            browser = browser_type.connect(
                **{
                    **connect_options,
                    "headers": {
                        "x-playwright-launch-options": json.dumps(launch_options),
                        **(connect_options.get("headers") or {}),
                    },
                }
            )
        else:
            browser = browser_type.launch(**launch_options)
        return browser

    return launch


@pytest.fixture(scope="package")
def browser(launch_browser: Callable[[], Browser]) -> Generator[Browser, None, None]:
    browser = launch_browser()
    yield browser
    browser.close()
