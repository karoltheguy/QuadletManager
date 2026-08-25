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
import json
import os
import tempfile
import pytest
from typing import Any, Callable, Dict, Generator, Optional
from playwright.sync_api import Browser, BrowserType, Playwright, sync_playwright

@pytest.fixture(scope="package", autouse=True)
def seed_e2e_database_if_empty():
    """Ensure the backend database has at least one server for E2E tests."""
    import subprocess
    import os

    # If the user is running the backend in Docker (e.g. in CI), we must seed the DB inside the container.
    docker_compose_cmd = ["docker", "compose", "-f", "docker-compose.test.yml"]
    
    in_docker = False
    try:
        # Check if docker-compose is available and the container is running
        result = subprocess.run(docker_compose_cmd + ["ps", "--services"], capture_output=True, text=True)
        if "quadlet-manager" in result.stdout:
            in_docker = True
    except Exception:
        pass

    try:
        import filelock
        lock_file = os.path.join(tempfile.gettempdir(), "quadlet_e2e_seed.lock")
        with filelock.FileLock(lock_file):
            if in_docker:
                subprocess.run(docker_compose_cmd + ["exec", "-T", "quadlet-manager", "python", "scripts/seed_test_db.py"], check=False)
            else:
                # Fallback to local python execution for local testing.
                # Must match core/database.py's DATABASE_PATH default, since the
                # locally-running app was not started with Docker's /data layout.
                script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts/seed_test_db.py"))
                seed_env = {**os.environ, "QUADLET_DB_PATH": os.environ.get("QUADLET_DB_PATH", "quadlets.db")}
                subprocess.run(["python", script_path], check=False, env=seed_env)
    except ImportError:
        # Fallback if filelock isn't available
        try:
            if in_docker:
                subprocess.run(docker_compose_cmd + ["exec", "-T", "quadlet-manager", "python", "scripts/seed_test_db.py"], check=False)
            else:
                script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts/seed_test_db.py"))
                seed_env = {**os.environ, "QUADLET_DB_PATH": os.environ.get("QUADLET_DB_PATH", "quadlets.db")}
                subprocess.run(["python", script_path], check=False, env=seed_env)
        except Exception:
            pass
    except Exception:
        pass



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


@pytest.fixture
def page(context: Any) -> Generator[Any, None, None]:
    page = context.new_page()

    console_logs = []
    page.on("console", lambda msg: console_logs.append(f"CONSOLE [{msg.type}]: {msg.text}"))
    page.on("pageerror", lambda err: console_logs.append(f"PAGE ERROR: {err.message}\n{err.stack}"))
    setattr(page, "_console_logs", console_logs)

    # Wrap page.goto to ensure main.js is loaded and executed before the test proceeds
    orig_goto = page.goto
    def robust_goto(*args, **kwargs):
        response = orig_goto(*args, **kwargs)
        try:
            if response and response.status == 200 and "localhost:8000" in page.url:
                page.wait_for_function("document.documentElement.dataset.appReady === '1'", timeout=10000)
        except Exception:
            pass
        return response

    page.goto = robust_goto
    yield page
    page.close()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()

    if rep.when == "call" and rep.failed:
        page = item.funcargs.get("page")
        if page:
            # Determine the workspace root dynamically relative to conftest.py
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            results_dir = os.path.join(root_dir, "test-results")
            try:
                os.makedirs(results_dir, exist_ok=True)
            except Exception as e:
                print(f"\n[E2E Artifact] Failed to create directory {results_dir}: {e}")
                return
            # Sanitize nodeid to create a safe filename
            safe_name = item.nodeid.replace("/", "_").replace(":", "_").replace("[", "_").replace("]", "_")

            # 1. Save screenshot
            screenshot_path = os.path.join(results_dir, f"{safe_name}.png")
            try:
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"\n[E2E Artifact] Saved failure screenshot to: {screenshot_path}")
            except Exception as e:
                print(f"\n[E2E Artifact] Failed to save screenshot: {e}")

            # 2. Save HTML source
            html_path = os.path.join(results_dir, f"{safe_name}.html")
            try:
                html_content = page.content()
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"[E2E Artifact] Saved HTML source to: {html_path}")
            except Exception as e:
                print(f"\n[E2E Artifact] Failed to save HTML source: {e}")

            # 3. Save console/error logs
            console_logs = getattr(page, "_console_logs", None)
            if console_logs is not None:
                log_path = os.path.join(results_dir, f"{safe_name}.log")
                try:
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(console_logs))
                    print(f"[E2E Artifact] Saved console logs to: {log_path}")
                except Exception as e:
                    print(f"\n[E2E Artifact] Failed to save console logs: {e}")
