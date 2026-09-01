"""Guard for issue #476: the browser suite must not hardcode its app URL.

Every hardcoded `http://localhost:8000` is a place where QM_APP_URL is quietly
ignored, and the resulting failure is a skip rather than an error. Reintroducing
one costs a run with no browser coverage, so it is worth failing on the literal
itself rather than on its consequences.
"""
import pathlib

import pytest

E2E_DIR = pathlib.Path(__file__).parent / "e2e"
LITERAL = "localhost:8000"
# The single definition every other module imports.
ALLOWED = {"app_url.py"}


def _offending_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        f"{path.name}:{number}: {line.strip()}"
        for number, line in enumerate(lines, start=1)
        if LITERAL in line
    ]


@pytest.mark.unit
def test_no_browser_test_hardcodes_the_app_url():
    """Browser tests must import BASE_URL, not spell out localhost:8000."""
    offenders = []
    for path in sorted(E2E_DIR.rglob("*.py")):
        if path.name in ALLOWED:
            continue
        offenders.extend(_offending_lines(path))
    assert offenders == [], (
        "These lines hardcode the app URL instead of importing it from "
        "tests.app_url, so QM_APP_URL would be ignored:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.unit
def test_app_url_honours_the_environment(monkeypatch):
    """QM_APP_URL must override the default, with any trailing slash dropped."""
    from tests.app_url import DEFAULT_APP_URL, app_base_url

    monkeypatch.delenv("QM_APP_URL", raising=False)
    assert app_base_url() == DEFAULT_APP_URL

    monkeypatch.setenv("QM_APP_URL", "http://localhost:9123/")
    assert app_base_url() == "http://localhost:9123"
