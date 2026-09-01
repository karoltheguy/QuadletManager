"""Tests for extracting Server-Sent Events client into ES module (sse.js).

These tests specify the migration for issue #445 where the Server-Sent Events client functions
move out of main.js into:
  - static/modules/sse.js: connectSSE, handleStatsUpdate, handleStatsError,
    cacheServerStats, detectUnexpectedlyStopped, isManualStop,
    createStatsErrorDOM, updatePollHealth, applyPollHealthBadges,
    updateCycleIndicator, fetchPollHealthSnapshot, handleQuadletsChanged,
    startStatsWaitTimeout
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

SSE_EXPORT_FUNCTIONS = [
    "connectSSE",
    "handleStatsUpdate",
    "handleStatsError",
    "cacheServerStats",
    "detectUnexpectedlyStopped",
    "isManualStop",
    "createStatsErrorDOM",
    "updatePollHealth",
    "applyPollHealthBadges",
    "updateCycleIndicator",
    "fetchPollHealthSnapshot",
    "handleQuadletsChanged",
    "startStatsWaitTimeout",
]

# handleQuadletsChanged left this list in #465. main.js imported it only to put it on
# the window bridge, and nothing outside main.js referenced it any more,
# so dropping the bridge entry left the import unused.
MAIN_JS_SSE_IMPORTS = [
    "connectSSE",
    "fetchPollHealthSnapshot",
    "applyPollHealthBadges",
    "handleStatsUpdate",
    "handleStatsError",
    "startStatsWaitTimeout",
]


@pytest.mark.unit
def test_sse_module_exports_its_functions():
    """Assert static/modules/sse.js exists and exports all thirteen SSE functions."""
    sse_js_path = REPO_ROOT / "static" / "modules" / "sse.js"
    assert sse_js_path.is_file(), (
        f"Expected sse module file to exist at {sse_js_path}; "
        "issue #445 extracts the Server-Sent Events client into this module"
    )

    content = sse_js_path.read_text(encoding="utf-8")
    for name in SSE_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/sse.js must export function {name}; "
            "it is part of the extracted SSE API for issue #445"
        )


@pytest.mark.unit
def test_main_js_no_longer_declares_the_sse_functions():
    """Assert static/main.js no longer declares any of the thirteen moved SSE functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in SSE_EXPORT_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}; "
            "it has moved to static/modules/sse.js for issue #445"
        )


@pytest.mark.unit
def test_main_js_imports_the_sse_module():
    """Assert static/main.js imports the required SSE functions from @qm/sse."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    sse_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/sse['\"]", content)
    assert sse_match, (
        "main.js must import from the '@qm/sse' bare specifier; issue #445"
    )

    imported_sse = {n.strip() for n in sse_match.group(1).split(",") if n.strip()}
    for name in MAIN_JS_SSE_IMPORTS:
        assert name in imported_sse, (
            f"main.js must import {name} from @qm/sse; issue #445"
        )


@pytest.mark.unit
def test_main_js_no_longer_holds_the_stats_wait_state():
    """Assert static/main.js no longer declares _statsReceived or _statsWaitTimeout."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert not re.search(r"\blet\s+_statsReceived\b", content), (
        "main.js must not declare _statsReceived; "
        "it has moved to static/modules/sse.js for issue #445"
    )
    assert not re.search(r"\blet\s+_statsWaitTimeout\b", content), (
        "main.js must not declare _statsWaitTimeout; "
        "it has moved to static/modules/sse.js for issue #445"
    )
