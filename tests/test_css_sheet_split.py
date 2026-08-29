"""
Tests for splitting design tokens into static/tokens.css (Issue #450).

Issue: templates/dashboard.html currently links a single monolithic stylesheet,
static/style.css. Issue #450 splits the design tokens out into static/tokens.css
and updates the dashboard template to emit one <link> per stylesheet, each
cache-busted with ?v=<mtime> via the asset_url() Jinja global.

The cascade contract requires:
1. static/tokens.css exists on disk and contains the design-token blocks
   (:root[data-theme="dark"], :root[data-theme="light"], [data-density="compact"],
   and --density-panel-padding).
2. The rendered dashboard HTML links /static/tokens.css?v=<mtime> before
   /static/style.css?v=<mtime> so token definitions precede the rules that consume them.
3. static/style.css no longer defines the split token blocks.

These tests assert this contract and are expected to FAIL until Issue #450
is implemented.
"""
import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from main import app

TOKENS_CSS_PATH = os.path.join(REPO_ROOT, "static", "tokens.css")
LAYOUT_CSS_PATH = os.path.join(REPO_ROOT, "static", "layout.css")
COMPONENTS_CSS_PATH = os.path.join(REPO_ROOT, "static", "components.css")
MONITOR_CSS_PATH = os.path.join(REPO_ROOT, "static", "monitor.css")
INSPECTOR_CSS_PATH = os.path.join(REPO_ROOT, "static", "inspector.css")
OVERVIEW_CSS_PATH = os.path.join(REPO_ROOT, "static", "overview.css")
STYLE_CSS_PATH = os.path.join(REPO_ROOT, "static", "style.css")


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


@pytest.mark.unit
def test_tokens_css_exists_on_disk():
    """static/tokens.css must exist on disk as a standalone stylesheet for tokens."""
    assert os.path.isfile(TOKENS_CSS_PATH), (
        f"static/tokens.css does not exist at {TOKENS_CSS_PATH}"
    )


@pytest.mark.unit
def test_dashboard_html_links_tokens_css_with_mtime(client):
    """The rendered dashboard HTML must contain /static/tokens.css?v=<mtime>
    where <mtime> is int(os.path.getmtime(...)) of static/tokens.css."""
    assert os.path.isfile(TOKENS_CSS_PATH), (
        f"static/tokens.css does not exist at {TOKENS_CSS_PATH}"
    )
    tokens_mtime = int(os.path.getmtime(TOKENS_CSS_PATH))
    response = client.get("/")
    assert response.status_code == 200
    assert f"/static/tokens.css?v={tokens_mtime}" in response.text


@pytest.mark.unit
def test_dashboard_tokens_css_link_precedes_style_css(client):
    """In rendered dashboard HTML, /static/tokens.css must appear before
    /static/style.css to protect the cascade."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    assert "/static/tokens.css" in html, (
        "dashboard HTML does not link /static/tokens.css"
    )
    assert "/static/style.css" in html, (
        "dashboard HTML does not link /static/style.css"
    )

    tokens_pos = html.index("/static/tokens.css")
    style_pos = html.index("/static/style.css")
    assert tokens_pos < style_pos, (
        f"/static/tokens.css (index {tokens_pos}) must appear before "
        f"/static/style.css (index {style_pos}) in rendered dashboard HTML"
    )


@pytest.mark.unit
def test_tokens_css_contains_design_token_blocks():
    """static/tokens.css must contain the design-token blocks (:root[data-theme="dark"],
    :root[data-theme="light"], and [data-density="compact"]) and the custom property
    --density-panel-padding."""
    assert os.path.isfile(TOKENS_CSS_PATH), (
        f"static/tokens.css does not exist at {TOKENS_CSS_PATH}"
    )
    with open(TOKENS_CSS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    assert ':root[data-theme="dark"]' in content, (
        'Expected :root[data-theme="dark"] selector in static/tokens.css'
    )
    assert ':root[data-theme="light"]' in content, (
        'Expected :root[data-theme="light"] selector in static/tokens.css'
    )
    assert '[data-density="compact"]' in content, (
        'Expected [data-density="compact"] selector in static/tokens.css'
    )
    assert '--density-panel-padding' in content, (
        'Expected --density-panel-padding custom property in static/tokens.css'
    )


@pytest.mark.unit
def test_style_css_no_longer_contains_split_tokens():
    """static/style.css must no longer define the split token blocks.

    Only the *definitions* move. style.css keeps its var(--density-panel-padding)
    references, so this asserts on the declaration form and the selector rather
    than on the bare property name.
    """
    assert os.path.isfile(STYLE_CSS_PATH), (
        f"static/style.css does not exist at {STYLE_CSS_PATH}"
    )
    with open(STYLE_CSS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    assert ':root[data-theme="light"] {' not in content, (
        'static/style.css still contains :root[data-theme="light"] {; '
        'token block should have been moved to static/tokens.css'
    )
    assert '[data-density="compact"] {' not in content, (
        'static/style.css still contains the [data-density="compact"] token block; '
        'it should have been moved to static/tokens.css'
    )
    assert '--density-panel-padding:' not in content, (
        'static/style.css still declares --density-panel-padding; '
        'the declaration should have been moved to static/tokens.css. '
        'var(--density-panel-padding) references are expected to remain.'
    )


@pytest.mark.unit
def test_layout_and_components_css_exist_on_disk():
    """static/layout.css and static/components.css must exist on disk and have non-empty content."""
    assert os.path.isfile(LAYOUT_CSS_PATH), (
        f"static/layout.css does not exist at {LAYOUT_CSS_PATH}"
    )
    with open(LAYOUT_CSS_PATH, "r", encoding="utf-8") as f:
        assert f.read().strip() != "", "static/layout.css is empty"

    assert os.path.isfile(COMPONENTS_CSS_PATH), (
        f"static/components.css does not exist at {COMPONENTS_CSS_PATH}"
    )
    with open(COMPONENTS_CSS_PATH, "r", encoding="utf-8") as f:
        assert f.read().strip() != "", "static/components.css is empty"


@pytest.mark.unit
def test_stylesheets_constant_declares_the_split_sheets_in_order():
    """STYLESHEETS must order tokens, layout and components ahead of style.css.

    This asserts relative order rather than the whole tuple: later issues in the
    #174 split insert further sheets between components.css and style.css, and
    pinning the exact tuple here would fail every one of them for no reason.
    """
    from api.routes import STYLESHEETS

    sheets = list(STYLESHEETS)
    for name in ("tokens.css", "layout.css", "components.css", "style.css"):
        assert name in sheets, f"Expected {name!r} in STYLESHEETS, got {sheets!r}"

    positions = [sheets.index(name) for name in
                 ("tokens.css", "layout.css", "components.css", "style.css")]
    assert positions == sorted(positions), (
        "Expected tokens.css, layout.css, components.css to precede style.css, "
        f"got {sheets!r}"
    )
    assert sheets[-1] == "style.css", (
        f"Expected style.css to link last, got {sheets[-1]!r}"
    )


@pytest.mark.unit
def test_dashboard_links_layout_before_components_before_style(client):
    """The rendered dashboard HTML must link layout.css and components.css in order before style.css."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    assert "/static/layout.css" in html, (
        "dashboard HTML does not link /static/layout.css"
    )
    assert "/static/components.css" in html, (
        "dashboard HTML does not link /static/components.css"
    )

    tokens_pos = html.index("/static/tokens.css")
    layout_pos = html.index("/static/layout.css")
    components_pos = html.index("/static/components.css")
    style_pos = html.index("/static/style.css")

    assert tokens_pos < layout_pos < components_pos < style_pos, (
        f"Expected stylesheet link order: /static/tokens.css ({tokens_pos}) < "
        f"/static/layout.css ({layout_pos}) < /static/components.css ({components_pos}) < "
        f"/static/style.css ({style_pos})"
    )


@pytest.mark.unit
def test_view_pane_sheets_exist_on_disk():
    """The three view-pane sheets must exist on disk with non-empty content."""
    for path in (MONITOR_CSS_PATH, INSPECTOR_CSS_PATH, OVERVIEW_CSS_PATH):
        assert os.path.isfile(path), f"{path} does not exist"
        with open(path, "r", encoding="utf-8") as f:
            assert f.read().strip() != "", f"{path} is empty"


@pytest.mark.unit
def test_stylesheets_constant_declares_the_view_pane_sheets_in_order():
    """STYLESHEETS must place the view-pane sheets after components.css and before style.css."""
    from api.routes import STYLESHEETS

    expected = (
        "tokens.css",
        "layout.css",
        "components.css",
        "monitor.css",
        "inspector.css",
        "overview.css",
        "style.css",
    )
    assert tuple(STYLESHEETS) == expected, (
        f"Expected STYLESHEETS to be {expected!r}, got {tuple(STYLESHEETS)!r}"
    )


@pytest.mark.unit
def test_dashboard_links_view_pane_sheets_in_order(client):
    """The rendered dashboard must link the view-pane sheets in STYLESHEETS order."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    ordered = [
        "/static/components.css",
        "/static/monitor.css",
        "/static/inspector.css",
        "/static/overview.css",
        "/static/style.css",
    ]
    for href in ordered:
        assert href in html, f"dashboard HTML does not link {href}"

    positions = [html.index(href) for href in ordered]
    assert positions == sorted(positions), (
        f"Expected link order {ordered}, got positions {positions}"
    )
