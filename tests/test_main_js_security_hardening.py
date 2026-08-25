"""
Structural tests for frontend security hardening in main.js (#161).
These verify source patterns directly — no running backend or browser required.
"""
import re
import pytest

from tests.js_source import read_static_js


def _src():
    return read_static_js()


@pytest.mark.unit
def test_update_monitoring_view_does_not_blind_spread_data():
    """updateMonitoringView must build filteredData from named fields, not Object.assign({}, data, ...)."""
    src = _src()
    m = re.search(r'function\s+updateMonitoringView\s*\(data\)(.*?)(?=\nfunction\s|\Z)', src, re.DOTALL)
    assert m, "updateMonitoringView not found"
    body = m.group(1)
    assert not re.search(r'Object\.assign\(\s*\{\s*\}\s*,\s*data\s*,', body), (
        "updateMonitoringView must not spread the full 'data' object — "
        "build filteredData from explicit known-safe fields instead"
    )


@pytest.mark.unit
def test_parse_percent_uses_global_replace():
    """parsePercent must not use a single-occurrence string replace for '%'."""
    src = _src()
    m = re.search(r'function\s+parsePercent\s*\(val\)(.*?)(?=\nfunction\s|\Z)', src, re.DOTALL)
    assert m, "parsePercent not found"
    body = m.group(1)
    assert "replace('%', '')" not in body, (
        "parsePercent must not use a single-occurrence string replace; "
        "use a global regex (/%/g) instead"
    )
    assert 'replace("%", "")' not in body, (
        "parsePercent must not use a single-occurrence string replace; "
        "use a global regex (/%/g) instead"
    )
