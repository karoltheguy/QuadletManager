"""Unit tests for the app_console_errors() filter (issue #217).

The filter is used by E2E tests to decide whether captured browser console/
page log entries represent genuine application errors, as opposed to noise
such as a cross-origin CDN asset failing to load (e.g. a third-party CDN
outage or ad-blocker interference should not fail our tests).
"""
import pytest

from tests.e2e.console_errors import app_console_errors


CDN_RESOURCE_LOAD_FAILURE = (
    "CONSOLE [error]: Failed trying to load default language strings "
    "NetworkError: Failed to execute 'importScripts' on "
    "'WorkerGlobalScope': The script at "
    "'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/"
    "base/common/worker/simpleWorker.nls.js' failed to load."
)

GENUINE_JS_EXCEPTION = (
    "PAGE ERROR: TypeError: Cannot read properties of undefined (reading 'foo')"
)

SAME_ORIGIN_RESOURCE_LOAD_FAILURE = (
    "CONSOLE [error]: Failed to load resource: the server responded with a "
    "status of 500 () http://localhost:8000/api/file/1"
)

PLAIN_APP_CONSOLE_ERROR = (
    "CONSOLE [error]: quadlet-lint: unexpected marker owner"
)

NON_ERROR_LOG_ENTRY = "CONSOLE [log]: editor ready"


@pytest.mark.unit
def test_app_console_errors_excludes_cross_origin_cdn_failures_but_keeps_real_errors():
    batch = [
        CDN_RESOURCE_LOAD_FAILURE,
        GENUINE_JS_EXCEPTION,
        SAME_ORIGIN_RESOURCE_LOAD_FAILURE,
        PLAIN_APP_CONSOLE_ERROR,
        NON_ERROR_LOG_ENTRY,
    ]

    result = app_console_errors(batch)

    assert CDN_RESOURCE_LOAD_FAILURE not in result, (
        "a cross-origin CDN resource-load failure must be excluded -- it is "
        "not an application error"
    )
    assert GENUINE_JS_EXCEPTION in result, (
        "a genuine uncaught JS exception (PAGE ERROR) must be kept"
    )
    assert SAME_ORIGIN_RESOURCE_LOAD_FAILURE in result, (
        "a same-origin resource-load failure must be kept -- the filter "
        "keys on origin, not on the mere presence of a load-failure message"
    )
    assert PLAIN_APP_CONSOLE_ERROR in result, (
        "a plain application console.error must be kept"
    )
    assert NON_ERROR_LOG_ENTRY not in result, (
        "a non-error console entry must never be treated as an application error"
    )
