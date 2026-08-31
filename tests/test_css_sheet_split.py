"""
Tests for the static/style.css sheet split (issues #450, #453, #454, #455).

templates/dashboard.html emits one <link> per entry in api.routes.STYLESHEETS,
each cache-busted with ?v=<mtime> via the asset_url() Jinja global. The split ran
over four issues and retired static/style.css entirely: tokens.css first, then
base, layout and components, then the view panes, then the leaf sheets, with
theme_customization.css last because it ends with the reduced-motion block.

These tests guard the cascade contract that ordering depends on. They assert
relative order rather than the exact tuple, so adding a sheet does not fail them.
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
TERMINAL_CSS_PATH = os.path.join(REPO_ROOT, "static", "terminal.css")
SETTINGS_CSS_PATH = os.path.join(REPO_ROOT, "static", "settings.css")
TREE_CSS_PATH = os.path.join(REPO_ROOT, "static", "tree.css")
THEME_CSS_PATH = os.path.join(REPO_ROOT, "static", "theme_customization.css")
BASE_CSS_PATH = os.path.join(REPO_ROOT, "static", "base.css")
EDITOR_CSS_PATH = os.path.join(REPO_ROOT, "static", "editor.css")


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
def test_dashboard_tokens_css_link_precedes_every_other_sheet(client):
    """In rendered dashboard HTML, /static/tokens.css must appear before every
    other stylesheet, since every one of them consumes the tokens."""
    from api.routes import STYLESHEETS

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    tokens_pos = html.index("/static/tokens.css")
    for sheet in STYLESHEETS:
        if sheet == "tokens.css":
            continue
        href = f"/static/{sheet}"
        assert href in html, f"dashboard HTML does not link {href}"
        assert tokens_pos < html.index(href), (
            f"/static/tokens.css must appear before {href} in rendered dashboard HTML"
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
def test_only_tokens_css_defines_the_split_tokens():
    """No sheet but tokens.css may define the split token blocks.

    Only the *definitions* are exclusive. Other sheets keep their
    var(--density-panel-padding) references, so this asserts on the declaration
    form and the selector rather than on the bare property name.
    """
    from api.routes import STYLESHEETS

    for sheet in STYLESHEETS:
        if sheet == "tokens.css":
            continue
        path = os.path.join(REPO_ROOT, "static", sheet)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        for marker in (':root[data-theme="light"] {', '[data-density="compact"] {',
                       '--density-panel-padding:'):
            assert marker not in content, (
                f"static/{sheet} defines {marker!r}; token definitions belong "
                "in static/tokens.css"
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
    """STYLESHEETS must order tokens, base, layout and components ahead of the rest.

    This asserts relative order rather than the whole tuple: later issues in the
    #174 split insert further sheets after components.css, and pinning the exact
    tuple here would fail every one of them for no reason.
    """
    from api.routes import STYLESHEETS

    sheets = list(STYLESHEETS)
    ordered = ["tokens.css", "base.css", "layout.css", "components.css"]
    for name in ordered:
        assert name in sheets, f"Expected {name!r} in STYLESHEETS, got {sheets!r}"

    positions = [sheets.index(name) for name in ordered]
    assert positions == sorted(positions), (
        f"Expected order {ordered}, got {sheets!r}"
    )
    assert "style.css" not in sheets, (
        "static/style.css was retired by issue #455; STYLESHEETS should not name it"
    )


@pytest.mark.unit
def test_dashboard_links_layout_before_components_before_style(client):
    """The rendered dashboard HTML must link tokens, base, layout then components."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    ordered = [
        "/static/tokens.css",
        "/static/base.css",
        "/static/layout.css",
        "/static/components.css",
    ]
    for href in ordered:
        assert href in html, f"dashboard HTML does not link {href}"

    positions = [html.index(href) for href in ordered]
    assert positions == sorted(positions), (
        f"Expected link order {ordered}, got positions {positions}"
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
    """STYLESHEETS must place the view-pane sheets after components.css.

    Asserts relative order rather than the whole tuple, for the same reason as
    test_stylesheets_constant_declares_the_split_sheets_in_order: #455 inserts
    four more sheets after overview.css.
    """
    from api.routes import STYLESHEETS

    sheets = list(STYLESHEETS)
    ordered = ["tokens.css", "layout.css", "components.css", "monitor.css",
               "inspector.css", "overview.css", "editor.css"]
    for name in ordered:
        assert name in sheets, f"Expected {name!r} in STYLESHEETS, got {sheets!r}"

    positions = [sheets.index(name) for name in ordered]
    assert positions == sorted(positions), (
        f"Expected order {ordered}, got {sheets!r}"
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
        "/static/editor.css",
    ]
    for href in ordered:
        assert href in html, f"dashboard HTML does not link {href}"

    positions = [html.index(href) for href in ordered]
    assert positions == sorted(positions), (
        f"Expected link order {ordered}, got positions {positions}"
    )


@pytest.mark.unit
def test_remaining_sheets_exist_on_disk():
    """The four closing sheets of the #174 split must exist with non-empty content."""
    for path in (TERMINAL_CSS_PATH, SETTINGS_CSS_PATH, TREE_CSS_PATH, THEME_CSS_PATH):
        assert os.path.isfile(path), f"{path} does not exist"
        with open(path, "r", encoding="utf-8") as f:
            assert f.read().strip() != "", f"{path} is empty"


@pytest.mark.unit
def test_stylesheets_constant_declares_the_remaining_sheets_in_order():
    """terminal.css must precede settings.css, and theme_customization.css must come last
    of the four, because .terminal-shell-select is declared in both terminal and settings
    regions and the reduced-motion block must override the animations it disables."""
    from api.routes import STYLESHEETS

    sheets = list(STYLESHEETS)
    ordered = ["overview.css", "terminal.css", "settings.css", "tree.css",
               "theme_customization.css"]
    for name in ordered:
        assert name in sheets, f"Expected {name!r} in STYLESHEETS, got {sheets!r}"

    positions = [sheets.index(name) for name in ordered]
    assert positions == sorted(positions), (
        f"Expected order {ordered}, got {sheets!r}"
    )
    assert sheets[-1] == "theme_customization.css", (
        "theme_customization.css must link last: it ends with the reduced-motion "
        f"block that overrides animations declared earlier. Got {sheets[-1]!r}"
    )


@pytest.mark.unit
def test_style_css_is_retired():
    """static/style.css is gone, and its remainder lives in base.css and editor.css.

    The reset, :focus-visible and the flat data-surface rule are app-wide, so they
    went to base.css. The Monaco host rules are a view pane, so they went to
    editor.css. Nothing was left that justified a sheet named "style".
    """
    assert not os.path.exists(os.path.join(REPO_ROOT, "static", "style.css")), (
        "static/style.css should have been retired by issue #455"
    )

    with open(BASE_CSS_PATH, "r", encoding="utf-8") as f:
        base = f.read()
    for marker in ("box-sizing: border-box", ":focus-visible", "anti-card-overuse"):
        assert marker in base, f"Expected {marker!r} in static/base.css"

    with open(EDITOR_CSS_PATH, "r", encoding="utf-8") as f:
        editor = f.read()
    for marker in ("#editor-pane", "#editor-container"):
        assert marker in editor, f"Expected {marker!r} in static/editor.css"


@pytest.mark.unit
def test_dashboard_links_the_remaining_sheets_in_order(client):
    """The rendered dashboard must link the four closing sheets in STYLESHEETS order."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    ordered = [
        "/static/overview.css",
        "/static/terminal.css",
        "/static/settings.css",
        "/static/tree.css",
        "/static/theme_customization.css",
    ]
    for href in ordered:
        assert href in html, f"dashboard HTML does not link {href}"

    positions = [html.index(href) for href in ordered]
    assert positions == sorted(positions), (
        f"Expected link order {ordered}, got positions {positions}"
    )
