"""E2E tests for client-side quadlet-lint wiring in the editor pane (Issue #199).

These tests render the REAL templates/partials/editor_pane.html template (via
Jinja2, using the exact context keys the real /api/file/{server_id} route
builds at api/routes.py:564-575) and serve it in place of a live backend
response by intercepting **/api/file/**. This exercises the actual production
wiring -- including the Monaco model URI construction -- rather than a
hand-written stub.

Defect under test: editor_pane.html currently builds the Monaco model URI
from {{ unit_name }} (always "<base>.service", per api/routes.py:557),
instead of {{ name }} (the real quadlet filename, e.g. "web.container"). The
vendored quadlet-lint's expectedSectionFor() keys off the file extension
(container/pod/network/volume/kube/build/image/artifact) and has no
"service" entry, so with the ".service" URI, rule QL050
(SECTION_FILE_MISMATCH) can never fire.
"""
import os

import pytest

from tests.e2e.console_errors import app_console_errors

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    Page = type('Page', (object,), {})
    def expect(x): pass

try:
    import jinja2
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT or not HAS_JINJA2,
    reason="Playwright and/or Jinja2 is not installed in this environment",
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

_jinja_env = None


def _env():
    global _jinja_env
    if _jinja_env is None:
        # autoescape matches starlette's Jinja2Templates, which the app uses.
        # #467 made it load-bearing: the file content now reaches the browser as
        # the #hidden-content textarea body rather than through `| safe`, so an
        # unescaped env here would render a different document than production.
        _jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
            autoescape=True,
        )
    return _jinja_env


def render_editor_pane(name, content, server_id=1, path=None, scope="global", user_role="editor"):
    """Render templates/partials/editor_pane.html the same way
    api/routes.py:fetch_file() does, reproducing its exact context keys and
    unit_name derivation.
    """
    if path is None:
        path = f"/etc/containers/systemd/{name}"

    base_name = name.rsplit(".", 1)[0]
    unit_name = f"{base_name}.service"
    quadlet_type = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    pod_name = base_name if quadlet_type == "pod" else None

    status_url = f"/api/systemctl/status/{server_id}?unit={unit_name}&scope={scope}"

    template = _env().get_template("partials/editor_pane.html")
    return template.render(
        server_id=server_id,
        name=name,
        path=path,
        scope=scope,
        unit_name=unit_name,
        content=content,
        status_url=status_url,
        user_role=user_role,
        quadlet_type=quadlet_type,
        pod_name=pod_name,
    )


def _swap_editor_pane(page, server_id, path, scope, name):
    page.evaluate(
        "(args) => htmx.ajax('GET', "
        "`/api/file/${args.server_id}?path=${encodeURIComponent(args.path)}"
        "&scope=${args.scope}&name=${args.name}`, "
        "{target: '#editor-pane', swap: 'outerHTML'})",
        {"server_id": server_id, "path": path, "scope": scope, "name": name},
    )


def _wait_for_editor(page):
    page.wait_for_function("() => window.editor != null", timeout=10_000)


def _get_markers(page, owner):
    return page.evaluate(
        "(owner) => monaco.editor.getModelMarkers({ owner }).map(m => "
        "({ code: (m.code && m.code.value) || m.code, message: m.message }))",
        owner,
    )


def _marker_codes(markers):
    codes = []
    for m in markers:
        code = m.get("code")
        if isinstance(code, dict):
            code = code.get("value")
        codes.append(code)
    return codes


@pytest.mark.e2e
def test_quadlet_lint_publishes_markers(page: Page):
    """Client-side quadlet-lint runs against the real editor pane and
    publishes markers under the 'quadlet-lint' owner."""
    content = "[Container]\nImag=nginx\n"
    editor_html = render_editor_pane("web.container", content)

    page.route(
        "**/api/file/**",
        lambda route: route.fulfill(status=200, headers={"Content-Type": "text/html"}, body=editor_html),
    )

    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    _swap_editor_pane(page, 1, "/etc/containers/systemd/web.container", "global", "web.container")
    _wait_for_editor(page)

    page.wait_for_function(
        "() => monaco.editor.getModelMarkers({ owner: 'quadlet-lint' }).length > 0",
        timeout=10_000,
    )

    markers = _get_markers(page, "quadlet-lint")
    assert markers, (
        "Expected quadlet-lint to publish at least one marker for 'Imag=nginx' "
        "(a typo of Image=) under owner 'quadlet-lint', got no markers."
    )
    first = markers[0]
    assert first, (
        f"Expected a diagnosable marker (code/message), got: {markers!r}"
    )


@pytest.mark.e2e
def test_quadlet_lint_file_type_rule_fires(page: Page):
    """Proves the defect: a .container file with a [Volume] section must
    trigger QL050 (SECTION_FILE_MISMATCH). This only works if the Monaco
    model URI reflects the real filename ('web.container'), not the
    '.service' systemd unit name."""
    content = "[Container]\nImage=nginx\n\n[Volume]\n"
    editor_html = render_editor_pane("web.container", content)

    page.route(
        "**/api/file/**",
        lambda route: route.fulfill(status=200, headers={"Content-Type": "text/html"}, body=editor_html),
    )

    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    _swap_editor_pane(page, 1, "/etc/containers/systemd/web.container", "global", "web.container")
    _wait_for_editor(page)

    page.wait_for_function(
        "() => monaco.editor.getModelMarkers({ owner: 'quadlet-lint' }).length > 0",
        timeout=10_000,
    )

    markers = _get_markers(page, "quadlet-lint")
    codes = _marker_codes(markers)
    assert "QL050" in codes, (
        "Expected a QL050 (SECTION_FILE_MISMATCH) marker for a [Volume] section "
        "inside a .container file, but none was found. This proves the Monaco "
        "model URI is not reflecting the real quadlet filename (web.container) -- "
        f"it is likely using the '.service' unit_name instead. Markers seen: {markers!r}"
    )


@pytest.mark.e2e
def test_client_and_server_marker_owners_coexist(page: Page):
    """Setting server-validate markers under owner 'quadlet' must not wipe
    (and must not be wiped by) client-side quadlet-lint markers under owner
    'quadlet-lint'."""
    content = "[Container]\nImag=nginx\n"
    editor_html = render_editor_pane("web.container", content)

    page.route(
        "**/api/file/**",
        lambda route: route.fulfill(status=200, headers={"Content-Type": "text/html"}, body=editor_html),
    )

    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    _swap_editor_pane(page, 1, "/etc/containers/systemd/web.container", "global", "web.container")
    _wait_for_editor(page)

    page.wait_for_function(
        "() => monaco.editor.getModelMarkers({ owner: 'quadlet-lint' }).length > 0",
        timeout=10_000,
    )

    # Mimic the server-validate path at static/main.js:2779.
    page.evaluate(
        "() => monaco.editor.setModelMarkers(window.editor.getModel(), 'quadlet', [{"
        "  severity: monaco.MarkerSeverity.Error,"
        "  message: 'server says nope',"
        "  startLineNumber: 1, startColumn: 1, endLineNumber: 1, endColumn: 2"
        "}])"
    )

    # Trigger a client re-lint by editing the model.
    page.evaluate(
        "() => window.editor.getModel().applyEdits([{"
        "  range: new monaco.Range(2, 1, 2, 1),"
        "  text: '\\n'"
        "}])"
    )

    page.wait_for_function(
        "() => monaco.editor.getModelMarkers({ owner: 'quadlet-lint' }).length > 0",
        timeout=10_000,
    )

    lint_markers = _get_markers(page, "quadlet-lint")
    server_markers = _get_markers(page, "quadlet")
    assert lint_markers, "Expected 'quadlet-lint' markers to survive a client re-lint after server markers were set."
    assert server_markers, "Expected 'quadlet' (server-validate) markers to survive a client re-lint of the same model."


@pytest.mark.e2e
def test_repeated_unit_swaps_produce_no_console_errors(page: Page):
    """Swapping between units repeatedly (A -> B -> A) must not throw --
    guards against duplicate Monaco URIs, disposed-model lint calls, or a
    dead 'quadlet-lint-ready' listener."""
    unit_a = ("web.container", "[Container]\nImage=nginx\n")
    unit_b = ("db.container", "[Container]\nImage=postgres\n")

    def handle_route(route):
        url = route.request.url
        if "name=db.container" in url:
            name, content = unit_b
        else:
            name, content = unit_a
        html = render_editor_pane(name, content)
        route.fulfill(status=200, headers={"Content-Type": "text/html"}, body=html)

    page.route("**/api/file/**", handle_route)

    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    for name, _ in (unit_a, unit_b, unit_a):
        _swap_editor_pane(page, 1, f"/etc/containers/systemd/{name}", "global", name)
        _wait_for_editor(page)
        page.wait_for_function(
            "() => monaco.editor.getModelMarkers({ owner: 'quadlet-lint' }).length >= 0",
            timeout=10_000,
        )
        # Give the debounced initial lint a moment to run/settle.
        page.wait_for_timeout(400)

    errors = app_console_errors(page._console_logs)
    assert not errors, f"Expected no console/page errors across repeated unit swaps, got: {errors!r}"


@pytest.mark.e2e
def test_lint_is_debounced(page: Page):
    """Rapid successive edits must collapse into a single quadlet-lint run,
    not one run per edit."""
    content = "[Container]\nImage=nginx\n"
    editor_html = render_editor_pane("web.container", content)

    page.route(
        "**/api/file/**",
        lambda route: route.fulfill(status=200, headers={"Content-Type": "text/html"}, body=editor_html),
    )

    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    _swap_editor_pane(page, 1, "/etc/containers/systemd/web.container", "global", "web.container")
    _wait_for_editor(page)

    page.wait_for_function(
        "() => monaco.editor.getModelMarkers({ owner: 'quadlet-lint' }).length >= 0",
        timeout=10_000,
    )

    # Instrument the lint sink: wrap setModelMarkers with a counter that only
    # counts calls made under the 'quadlet-lint' owner, then reset it to 0.
    page.evaluate(
        "() => {"
        "  const orig = monaco.editor.setModelMarkers.bind(monaco.editor);"
        "  window.__origSetModelMarkers = orig;"
        "  window.__quadletLintCallCount = 0;"
        "  monaco.editor.setModelMarkers = function(model, owner, markers) {"
        "    if (owner === 'quadlet-lint') { window.__quadletLintCallCount++; }"
        "    return orig(model, owner, markers);"
        "  };"
        "}"
    )

    # Apply 5 rapid consecutive edits within a single debounce window.
    page.evaluate(
        "() => {"
        "  const model = window.editor.getModel();"
        "  for (let i = 0; i < 5; i++) {"
        "    model.setValue(`[Container]\\nImage=nginx${i}\\n`);"
        "  }"
        "}"
    )

    # Wait comfortably past the ~200ms debounce window.
    page.wait_for_timeout(600)

    count = page.evaluate("() => window.__quadletLintCallCount")
    assert count == 1, (
        f"Expected exactly 1 quadlet-lint run after 5 rapid edits within one "
        f"debounce window, got {count}."
    )


@pytest.mark.e2e
def test_swap_during_debounce_produces_no_page_error(page: Page):
    """Editing a model and swapping panes WITHIN the debounce window must not
    let a pending debounced lint fire against a model that teardown already
    disposed."""
    unit_a = ("web.container", "[Container]\nImage=nginx\n")
    unit_b = ("db.container", "[Container]\nImage=postgres\n")

    def handle_route(route):
        url = route.request.url
        if "name=db.container" in url:
            name, content = unit_b
        else:
            name, content = unit_a
        html = render_editor_pane(name, content)
        route.fulfill(status=200, headers={"Content-Type": "text/html"}, body=html)

    page.route("**/api/file/**", handle_route)

    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    _swap_editor_pane(page, 1, "/etc/containers/systemd/web.container", "global", "web.container")
    _wait_for_editor(page)

    # An edit marks the pane dirty, which triggers main.js's htmx:confirm
    # "discard unsaved changes?" native dialog before it allows a swap of
    # #editor-pane. Auto-accept it, as a real user discarding their edit
    # would, so the race we're targeting actually gets exercised.
    page.once("dialog", lambda dialog: dialog.accept())

    # Apply an edit to the model, then IMMEDIATELY (no wait -- inside the
    # ~200ms debounce window) trigger the swap to unit B.
    page.evaluate(
        "() => window.editor.getModel().applyEdits([{"
        "  range: new monaco.Range(2, 1, 2, 1),"
        "  text: '\\n'"
        "}])"
    )
    _swap_editor_pane(page, 1, "/etc/containers/systemd/db.container", "global", "db.container")

    _wait_for_editor(page)
    page.wait_for_function(
        "() => monaco.editor.getModelMarkers({ owner: 'quadlet-lint' }).length >= 0",
        timeout=10_000,
    )

    # Wait a further ~600ms so any orphaned timer against the disposed model
    # would have had a chance to fire.
    page.wait_for_timeout(600)

    errors = app_console_errors(page._console_logs)
    assert not errors, (
        f"Expected no console/page errors from a pending debounced lint racing "
        f"a pane swap, got: {errors!r}"
    )
