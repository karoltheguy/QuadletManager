"""E2E test for issue #474: a saved theme must apply on the auth pages.

`static/auth_theme_boot.js` was reading `qm-theme` while `toggleTheme` writes
`qm-theme-override`, so the auth pages always rendered in the default theme.
The unit tests in tests/test_auth_theme_boot.py assert on the script's source
text, which cannot catch a key that no page exercises. This one drives a real
page instead.

It targets /change-password rather than /login, because both templates load the
same boot script but only /change-password is reachable in the test
environment: docker-compose.test.yml sets DEV_AUTO_LOGIN=1, under which
get_optional_user_role always reports a session and GET /login therefore
redirects to /.
"""
import pytest

try:
    from playwright.sync_api import Browser
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Browser = typing.Any

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment"
)

from tests.app_url import BASE_URL
AUTH_PAGE_URL = BASE_URL + "/change-password"


@pytest.fixture
def auth_page(browser: Browser):
    """A plain page in its own context.

    Not the shared `page` fixture: its goto wrapper waits ten seconds for
    `dataset.appReady`, which only the dashboard sets. A private context also
    keeps this test's localStorage writes away from every other test.
    """
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


@pytest.mark.e2e
@pytest.mark.parametrize("saved_theme", ["dark", "light"])
def test_auth_page_applies_the_saved_theme_override(auth_page, saved_theme):
    """A qm-theme-override value written by toggleTheme must reach <html data-theme>."""
    page = auth_page
    try:
        response = page.goto(AUTH_PAGE_URL)
    except Exception:
        pytest.skip(f"Backend is not running on {BASE_URL} — skipping E2E tests.")
    if response is None or response.status != 200:
        pytest.skip(f"GET {AUTH_PAGE_URL} did not return 200 — skipping E2E tests.")

    assert "auth_theme_boot" in page.content(), (
        f"{AUTH_PAGE_URL} did not render the auth template (landed on {page.url}). "
        "This test needs a page that loads static/auth_theme_boot.js."
    )

    # Write the key toggleTheme persists, then reload so the boot script reads
    # it during the same document load it is meant to protect from a flash.
    page.evaluate(
        "theme => localStorage.setItem('qm-theme-override', theme)", saved_theme
    )
    page.reload()

    applied = page.evaluate("document.documentElement.dataset.theme")
    assert applied == saved_theme, (
        f"Auth page must apply the saved '{saved_theme}' theme from "
        f"localStorage['qm-theme-override'], but data-theme was {applied!r}. "
        "static/auth_theme_boot.js is probably reading the wrong key (#474)."
    )
