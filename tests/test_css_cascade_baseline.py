"""
Tests for CSS cascade baseline and stylesheet split preservation.

Background:
static/style.css is being split into smaller stylesheets over several pull requests.
Each split is a pure MOVE of rule blocks between files. The move will change the
relative order of some blocks, so these tests do not assert source order of the
blocks. They assert only that the set of rule blocks is unchanged, i.e. nothing was
lost, duplicated, or rewritten during a move.

The contract requires:
1. `STYLESHEETS` constant in `api.routes` is an importable, ordered list/tuple of stylesheet
   names starting with 'tokens.css'.
2. The rendered dashboard HTML links every stylesheet in `STYLESHEETS` in declared order.
3. The baseline fixture `tests/fixtures/css_cascade_baseline.txt` exists on disk.
4. The live rule blocks across all stylesheets listed in `STYLESHEETS` match the committed
   baseline fixture.

These tests assert this contract and are expected to FAIL until the STYLESHEETS constant
and the cascade baseline fixture are implemented.
"""
import collections
import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from main import app
from tests.css_source import rule_blocks, strip_comments


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


@pytest.mark.unit
def test_stylesheets_constant_is_importable_and_ordered():
    """Assert STYLESHEETS is a non-empty list or tuple of str, that every entry ends with '.css',
    and that STYLESHEETS[0] == 'tokens.css'."""
    from api.routes import STYLESHEETS

    assert isinstance(STYLESHEETS, (list, tuple)), (
        f"Expected STYLESHEETS to be a list or tuple, got {type(STYLESHEETS).__name__}"
    )
    assert len(STYLESHEETS) > 0, "STYLESHEETS must not be empty"
    assert all(isinstance(sheet, str) and sheet.endswith(".css") for sheet in STYLESHEETS), (
        "Every entry in STYLESHEETS must be a string ending with '.css'"
    )
    assert STYLESHEETS[0] == "tokens.css", (
        f"Expected first stylesheet to be 'tokens.css', got {STYLESHEETS[0]!r}"
    )


@pytest.mark.unit
def test_dashboard_links_every_stylesheet_in_declared_order(client):
    """Render GET '/' with the client. For each name in STYLESHEETS, assert the substring
    f'/static/{name}?v=' appears in response.text. Then assert the positions of those substrings
    within response.text are strictly increasing, so the rendered link order matches STYLESHEETS."""
    from api.routes import STYLESHEETS

    response = client.get("/")
    assert response.status_code == 200

    html = response.text
    positions = []
    for sheet in STYLESHEETS:
        link_substr = f"/static/{sheet}?v="
        assert link_substr in html, (
            f"Expected {link_substr!r} in rendered dashboard HTML"
        )
        positions.append(html.index(link_substr))

    for i in range(len(positions) - 1):
        assert positions[i] < positions[i + 1], (
            f"Stylesheet {STYLESHEETS[i]!r} (index {positions[i]}) must appear before "
            f"{STYLESHEETS[i + 1]!r} (index {positions[i + 1]}) in rendered dashboard HTML"
        )


@pytest.mark.unit
def test_cascade_baseline_fixture_exists():
    """Assert os.path.isfile(os.path.join(REPO_ROOT, 'tests', 'fixtures', 'css_cascade_baseline.txt'))."""
    fixture_path = os.path.join(REPO_ROOT, "tests", "fixtures", "css_cascade_baseline.txt")
    assert os.path.isfile(fixture_path), (
        f"Cascade baseline fixture does not exist at {fixture_path}"
    )


@pytest.mark.unit
def test_rule_blocks_match_the_committed_baseline():
    """Read the fixture: one normalized rule block per line, already sorted.
    Build the live set by reading each file in STYLESHEETS from REPO_ROOT/static, in STYLESHEETS
    order, joining their contents with '\\n', then strip_comments and rule_blocks.
    Assert collections.Counter(live_blocks) == collections.Counter(fixture_lines).
    On failure the message must name how many blocks are only in the live CSS and how many are
    only in the fixture, and show up to 3 examples of each truncated to 120 characters."""
    from api.routes import STYLESHEETS

    fixture_path = os.path.join(REPO_ROOT, "tests", "fixtures", "css_cascade_baseline.txt")
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture_lines = [line.strip() for line in f if line.strip()]

    live_contents = []
    for sheet in STYLESHEETS:
        sheet_path = os.path.join(REPO_ROOT, "static", sheet)
        with open(sheet_path, "r", encoding="utf-8") as f:
            live_contents.append(f.read())

    combined_css = "\n".join(live_contents)
    live_blocks = rule_blocks(strip_comments(combined_css))

    live_counter = collections.Counter(live_blocks)
    fixture_counter = collections.Counter(fixture_lines)

    only_live = list((live_counter - fixture_counter).elements())
    only_fixture = list((fixture_counter - live_counter).elements())

    live_examples = [b[:120] for b in only_live[:3]]
    fixture_examples = [b[:120] for b in only_fixture[:3]]

    failure_msg = (
        f"Rule blocks do not match committed baseline.\n"
        f"Blocks only in live CSS ({len(only_live)}): {live_examples}\n"
        f"Blocks only in fixture ({len(only_fixture)}): {fixture_examples}"
    )

    assert live_counter == fixture_counter, failure_msg
