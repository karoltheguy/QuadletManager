import logging

import pytest

from main import _PollingAccessLogFilter


@pytest.mark.unit
def test_polling_access_log_filtered_out():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="%s - \"%s %s HTTP/%s\" %s",
        args=("127.0.0.1:1234", "GET", "/api/overview", "1.1", "200"),
        exc_info=None,
    )
    assert _PollingAccessLogFilter().filter(record) is False


@pytest.mark.unit
def test_filter_drops_overview_with_query_string():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="%s - \"%s %s HTTP/%s\" %s",
        args=("127.0.0.1:1234", "GET", "/api/overview?since=5m", "1.1", "200"),
        exc_info=None,
    )
    assert _PollingAccessLogFilter().filter(record) is False

    record2 = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="%s - \"%s %s HTTP/%s\" %s",
        args=("127.0.0.1:1234", "GET", "/api/poll-health?x=1", "1.1", "200"),
        exc_info=None,
    )
    assert _PollingAccessLogFilter().filter(record2) is True


@pytest.mark.unit
def test_non_polling_access_log_passes_through():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="%s - \"%s %s HTTP/%s\" %s",
        args=("127.0.0.1:1234", "GET", "/api/servers", "1.1", "200"),
        exc_info=None,
    )
    assert _PollingAccessLogFilter().filter(record) is True
