"""Navigating to the app under test, in one place (issue #476).

Roughly twenty tests opened with the same four-line guard: goto inside a
try/except, `pytest.skip` on failure. Keeping one copy makes the skip message
uniform and means a change to how the suite reaches the app is a single edit.
"""
import pytest

from tests.app_url import BASE_URL


def goto_app(page, path="/", **kwargs):
    """Open `path` on the app under test, or skip when nothing answers.

    Returns the Playwright response, so callers that check the status still can.
    A missing backend is a skip rather than a failure because the browser suite
    is expected to be runnable without one; see docs/TESTING.md.
    """
    try:
        return page.goto(BASE_URL + path, **kwargs)
    except Exception:
        pytest.skip(f"Backend is not running at {BASE_URL} — skipping E2E tests.")
