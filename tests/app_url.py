"""Where the browser tests expect to find a running app (issue #476).

One definition, imported by every caller. The browser suite used to carry
21 copies of a hardcoded `http://localhost:8000`, which made the scratch app in
`scripts/browser-e2e.sh` impossible to run on a free port and made the failure
mode silent: `tests/conftest.py` skips every page-fixture test when nothing
answers at this URL, so a suite pointed at the wrong port reports a green run
with zero browser coverage rather than an error.

Set QM_APP_URL to point the suite at an app you already have. It must be
exported for the whole pytest invocation, not just for the app process, because
the reachability gate in tests/conftest.py reads it too.
"""
import os

DEFAULT_APP_URL = "http://localhost:8000"


def app_base_url() -> str:
    """The base URL of the app under test, without a trailing slash."""
    return os.environ.get("QM_APP_URL", DEFAULT_APP_URL).rstrip("/")


BASE_URL = app_base_url()
