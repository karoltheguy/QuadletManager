"""Tests for moving shared frontend state into static/modules/state.js (issue #391).

These tests specify the upcoming migration where mutable frontend state is moved
from static/main.js into an ES module static/modules/state.js, resolved via an
import map rendered in templates/dashboard.html.
"""
import pathlib
import re
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from main import app
from tests.js_source import read_static_js, static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

COLLECTION_NAMES = [
    "lastStatsPerServer",
    "runningContainersBySid",
    "manualStops",
    "pendingStarts",
    "chartColorByName",
    "monitorChartSelection",
    "_terminalTabs",
    "_logTabs",
]

SCALAR_NAMES = [
    "activeServerId",
    "monitorContainerFilter",
    "_selectedContainerStem",
    "_selectedContainerServerId",
    "_selectedContainerScope",
    "_selectedContainerType",
    "_quadletRestored",
    "_monitoringServerId",
    "_monitorChartMinutes",
    "cpuHistoryChart",
    "memHistoryChart",
    "_activeTerminalTabKey",
    "_activeLogTabKey",
]

ALL_SHARED_NAMES = COLLECTION_NAMES + SCALAR_NAMES


@pytest.mark.unit
def test_import_map_is_registered_as_a_jinja_global():
    """Verify module_import_map is registered as a global in Jinja2 templates."""
    import api.routes as routes
    from api.routes import templates

    assert hasattr(routes, "module_import_map"), "module_import_map is not defined in api.routes"
    from api.routes import module_import_map

    assert templates.env.globals.get("module_import_map") is module_import_map


@pytest.mark.unit
def test_import_map_maps_every_static_module_to_a_versioned_url():
    """Verify module_import_map() maps every static/modules/*.js file to a versioned URL and @qm/state."""
    import api.routes as routes

    assert hasattr(routes, "module_import_map"), "module_import_map is not defined in api.routes"
    from api.routes import module_import_map

    import_map = module_import_map()
    assert isinstance(import_map, dict), (
        "module_import_map must return a mapping so the template can render it "
        "with Jinja's tojson rather than disabling auto-escaping with |safe"
    )
    imports = import_map.get("imports", import_map)

    assert "@qm/state" in imports, "Bare specifier '@qm/state' not found in import map"
    assert re.match(r"^/static/modules/state\.js\?v=\d+$", str(imports["@qm/state"])), (
        f"Expected @qm/state to map to /static/modules/state.js?v=<digits>, got {imports['@qm/state']}"
    )

    modules_dir = REPO_ROOT / "static" / "modules"
    assert modules_dir.is_dir(), f"Expected the module directory to exist at {modules_dir}"
    for module_file in modules_dir.glob("*.js"):
        pattern = rf"^/static/modules/{re.escape(module_file.name)}\?v=\d+$"
        assert any(re.match(pattern, str(v)) for v in imports.values()), (
            f"No versioned import map entry found for {module_file.name} in {imports}"
        )


@pytest.mark.unit
def test_dashboard_emits_the_import_map_before_any_module_script():
    """Verify the dashboard HTML emits <script type="importmap"> before any module scripts."""
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200
            html = response.text

    assert '<script type="importmap">' in html, (
        'Dashboard HTML does not contain <script type="importmap">'
    )

    importmap_index = html.index('<script type="importmap">')
    module_matches = list(re.finditer(r'<script\b[^>]*type=["\']module["\'][^>]*>', html, re.IGNORECASE))
    assert module_matches, 'Dashboard HTML must contain at least one type="module" script tag'

    for match in module_matches:
        assert importmap_index < match.start(), (
            f"Import map (at index {importmap_index}) must precede module script '{match.group(0)}' (at index {match.start()})"
        )


@pytest.mark.unit
def test_state_module_exports_the_shared_collections():
    """Verify static/modules/state.js exports all eight shared collection objects as const."""
    state_js_path = REPO_ROOT / "static" / "modules" / "state.js"
    assert state_js_path.is_file(), f"Expected state module file to exist at {state_js_path}"

    content = state_js_path.read_text(encoding="utf-8")
    for name in COLLECTION_NAMES:
        pattern = rf"\bexport\s+const\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/state.js must export const {name}"
        )


@pytest.mark.unit
def test_state_module_exports_the_reassignable_scalars():
    """Verify static/modules/state.js exports a state object containing all 13 scalar fields."""
    state_js_path = REPO_ROOT / "static" / "modules" / "state.js"
    assert state_js_path.is_file(), f"Expected state module file to exist at {state_js_path}"

    content = state_js_path.read_text(encoding="utf-8")
    state_match = re.search(r"export\s+const\s+state\s*=\s*\{([^}]*)\}", content, re.DOTALL)
    assert state_match, "static/modules/state.js must contain 'export const state = { ... }'"

    state_body = state_match.group(1)
    for name in SCALAR_NAMES:
        key_pattern = rf"\b{re.escape(name)}\s*:"
        assert re.search(key_pattern, state_body), (
            f"state object in static/modules/state.js must define key '{name}'"
        )


@pytest.mark.unit
def test_main_js_declares_no_shared_state():
    """Verify main.js does not declare any of the 21 shared state variables."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    offending_declarations = []
    for name in ALL_SHARED_NAMES:
        pattern = rf"^(?:const|let|var)\s+{re.escape(name)}\b"
        if re.search(pattern, content, re.MULTILINE):
            offending_declarations.append(name)

    assert not offending_declarations, (
        f"Found shared state declarations in main.js: {offending_declarations}"
    )


@pytest.mark.unit
def test_bridge_exposes_scalars_as_accessors_not_copies():
    """Verify main.js defines accessors via Object.defineProperties instead of copying scalars into Object.assign."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert "Object.defineProperties(window," in content, (
        "main.js must call Object.defineProperties(window, ...) to bridge scalar state accessors"
    )

    bridge_match = re.search(
        r"Object\.assign\s*\(\s*window\s*,\s*\{(.*?)\}\s*\)",
        content,
        re.DOTALL,
    )
    assert bridge_match, "Object.assign(window, { ... }) block not found in main.js"
    bridge_body = bridge_match.group(1)

    offending_scalars = []
    for scalar in SCALAR_NAMES:
        if re.search(rf"\b{re.escape(scalar)}\s*:", bridge_body):
            offending_scalars.append(scalar)

    assert not offending_scalars, (
        f"Found scalar properties copied by value in Object.assign(window, {{ ... }}): {offending_scalars}"
    )


@pytest.mark.unit
def test_main_js_imports_the_shared_state_module():
    """main.js must reach the shared state through the import map's bare specifier.

    Without this, main.js could satisfy the "declares no shared state" test while
    referencing names that no longer exist anywhere, which only e2e would catch.
    Importing by bare specifier rather than a relative path is what puts the
    module under the same mtime cache busting as the template script tags.
    """
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/state['\"]", content)
    assert match, "main.js must import from the '@qm/state' bare specifier"

    imported = {n.strip() for n in match.group(1).split(",") if n.strip()}
    assert "state" in imported, "main.js must import the `state` object holding the scalars"

    # Every collection main.js still REFERENCES must be imported, but it need not
    # import all of them. As #174 moves clusters into modules, each collection's
    # last consumer in main.js leaves with its cluster: chartColorByName went to
    # charts.js in #432. Demanding the full list would force main.js to keep
    # imports it never uses, which is exactly what a static analyzer flags.
    body = content[match.end():]
    referenced = [n for n in COLLECTION_NAMES if re.search(rf"\b{re.escape(n)}\b", body)]
    missing = [n for n in referenced if n not in imported]
    assert not missing, f"main.js references these collections without importing them: {missing}"
