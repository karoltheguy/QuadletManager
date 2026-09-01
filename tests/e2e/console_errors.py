"""Helpers for asserting on captured browser console/page errors in E2E tests."""
import re
from urllib.parse import urlparse

from tests.app_url import BASE_URL

# host:port of the app under test, so the cross-origin filter below follows
# QM_APP_URL instead of assuming the default port (#476).
_APP_HOST = urlparse(BASE_URL).netloc

_URL_RE = re.compile(r"https?://[^\s'\"]+")

_LOAD_FAILURE_MARKERS = (
    "importscripts",
    "networkerror",
    "failed to load resource",
    "net::err",
    "err_",
)


def app_console_errors(logs, app_host=None):
    """Return the console/page error entries that count as application errors.

    Keeps every "PAGE ERROR" entry unconditionally (an uncaught JS exception
    is application code by definition). For "CONSOLE [error]" entries, keeps
    them unless the entry looks like a cross-origin resource/network load
    failure: it must both match a load-failure marker (e.g. importScripts,
    NetworkError, "Failed to load resource", net::ERR, ERR_) AND contain at
    least one http(s) URL whose host does not include app_host. This filters
    out noisy cross-origin CDN/asset failures (see issue #217) while still
    keeping genuine application console.error messages and same-origin
    resource-load failures.

    All other log entries (e.g. "CONSOLE [log]") are ignored.

    app_host defaults to the host:port of QM_APP_URL.
    """
    if app_host is None:
        app_host = _APP_HOST
    kept = []
    for entry in logs:
        if "PAGE ERROR" in entry:
            kept.append(entry)
            continue
        if "CONSOLE [error]" not in entry:
            continue

        lowered = entry.lower()
        has_marker = any(marker in lowered for marker in _LOAD_FAILURE_MARKERS)
        urls = _URL_RE.findall(entry)
        all_cross_origin = bool(urls) and all(app_host not in url for url in urls)

        if has_marker and all_cross_origin:
            continue
        kept.append(entry)

    return kept
