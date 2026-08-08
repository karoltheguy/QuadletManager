import pytest
"""Tests for frontend/backend unit naming parity (issue #340).

Verifies that static/main.js mirrors services/quadlet_naming.py's
SUFFIXED_QUADLET_TYPES and unit_name_for() logic instead of hand-rolling
stem + '.service' in multiple places, and that templates/partials/
quadlet_tree.html exposes the quadlet type needed to drive that logic.
"""
import os

MAIN_JS = os.path.join(os.path.dirname(__file__), '..', 'static', 'main.js')
TREE_HTML = os.path.join(os.path.dirname(__file__), '..', 'templates', 'partials', 'quadlet_tree.html')
EDITOR_PANE_HTML = os.path.join(os.path.dirname(__file__), '..', 'templates', 'partials', 'editor_pane.html')


def _read_js():
    with open(MAIN_JS, 'r') as f:
        return f.read()


def _read_tree_html():
    with open(TREE_HTML, 'r') as f:
        return f.read()


def _read_editor_pane():
    with open(EDITOR_PANE_HTML, 'r') as f:
        return f.read()


# =============================================================================
# Shared SUFFIXED_QUADLET_TYPES / unitNameFor helper
# =============================================================================


@pytest.mark.unit
def test_suffixed_quadlet_types_set_present():
    js = _read_js()
    assert "SUFFIXED_QUADLET_TYPES" in js, \
        "main.js must define a SUFFIXED_QUADLET_TYPES set mirroring services/quadlet_naming.py"


@pytest.mark.unit
def test_suffixed_quadlet_types_contains_all_five_types():
    js = _read_js()
    start = js.find("SUFFIXED_QUADLET_TYPES")
    assert start != -1, "SUFFIXED_QUADLET_TYPES must be defined before checking its contents"
    end = js.find("\n", js.find("\n", start) + 1)
    definition = js[start:end if end != -1 else len(js)]
    for quadlet_type in ('pod', 'volume', 'network', 'image', 'build'):
        assert quadlet_type in definition, \
            f"SUFFIXED_QUADLET_TYPES definition must include '{quadlet_type}'"


@pytest.mark.unit
def test_unit_name_for_function_defined():
    js = _read_js()
    assert "function unitNameFor(" in js, \
        "main.js must define a unitNameFor function mirroring unit_name_for() in services/quadlet_naming.py"


@pytest.mark.unit
def test_hand_rolled_unit_name_pattern_removed():
    """The old hand-rolled unitName = stem + '.service' pattern must be gone,
    replaced by calls to the shared unitNameFor helper."""
    js = _read_js()
    assert "unitName = stem + '.service'" not in js, \
        "unitName = stem + '.service' must be removed in favor of unitNameFor(stem/fileName)"


# =============================================================================
# Call sites use the shared helper
# =============================================================================


@pytest.mark.unit
def test_show_file_context_menu_uses_unit_name_for():
    js = _read_js()
    start = js.find("window.showFileContextMenu = function")
    assert start != -1, "showFileContextMenu must be defined"
    end = js.find("\nwindow.", start + 1)
    body = js[start:end if end != -1 else len(js)]
    assert "unitNameFor(fileName)" in body, \
        "showFileContextMenu must derive its unit name via unitNameFor(fileName)"


@pytest.mark.unit
def test_tail_logs_from_panel_uses_unit_name_for():
    js = _read_js()
    start = js.find("window.tailLogsFromPanel = function")
    assert start != -1, "tailLogsFromPanel must be defined"
    end = js.find("\nwindow.", start + 1)
    body = js[start:end if end != -1 else len(js)]
    assert "unitNameFor" in body, \
        "tailLogsFromPanel must derive its unit name via unitNameFor"
    assert "+ '.service'" not in body, \
        "tailLogsFromPanel must not derive its unit name by concatenating '.service'"


# =============================================================================
# Template exposes quadlet type
# =============================================================================


@pytest.mark.unit
def test_quadlet_tree_button_has_data_type_attribute():
    html = _read_tree_html()
    assert "data-type" in html, \
        "quadlet_tree.html must give the quadlet tree button a data-type attribute"


# =============================================================================
# selectContainerStem accepts the quadlet type
# =============================================================================


@pytest.mark.unit
def test_select_container_stem_accepts_type_parameter():
    js = _read_js()
    start = js.find("window.selectContainerStem = function")
    assert start != -1, "selectContainerStem must be defined"
    end = js.find("\n", start)
    signature = js[start:end]
    assert "type" in signature.split("function")[1].split(")")[0], \
        "selectContainerStem must accept a fourth parameter for the quadlet type"


@pytest.mark.unit
def test_select_container_stem_assigns_selected_container_type():
    js = _read_js()
    start = js.find("window.selectContainerStem = function")
    assert start != -1, "selectContainerStem must be defined"
    end = js.find("\nwindow.", start + 1)
    body = js[start:end if end != -1 else len(js)]
    assert "window._selectedContainerType" in body, \
        "selectContainerStem must assign window._selectedContainerType from its new parameter"


# =============================================================================
# stemFromUnitName cannot invert a unit name back to a stem by guessing
# (issue #340 follow-up)
#
# podman's generator maps BOTH `my.pod` and `my-pod.container` to the same
# unit name `my-pod.service`. Stripping a `-pod` suffix from the unit name is
# correct for the first source file and wrong for the second, so the guess in
# stemFromUnitName(unitName) is unresolvable from the unit name alone. The
# fix is to stop guessing: pass the quadlet type along with the request, the
# same way `scope` and `action` are already passed, and let
# stemFromUnitName use it instead of inferring it.
# =============================================================================


@pytest.mark.unit
def test_stem_from_unit_name_accepts_quadlet_type_parameter():
    js = _read_js()
    assert "function stemFromUnitName(unitName, quadletType)" in js, \
        "stemFromUnitName must accept a second quadletType parameter instead of guessing the type from the unit name"


@pytest.mark.unit
def test_before_request_handler_calls_stem_from_unit_name_with_type():
    js = _read_js()
    start = js.find("document.body.addEventListener('htmx:beforeRequest'")
    assert start != -1, "htmx:beforeRequest handler must be defined"
    end = js.find("\ndocument.body.addEventListener('htmx:responseError'", start)
    body = js[start:end if end != -1 else len(js)]
    assert "stemFromUnitName(unitName)." not in body, \
        "the htmx:beforeRequest handler must not call stemFromUnitName with only one argument"
    assert "stemFromUnitName(unitName, " in body, \
        "the htmx:beforeRequest handler must call stemFromUnitName with a second quadlet type argument"


@pytest.mark.unit
def test_before_request_handler_reads_quadlet_type_from_params():
    js = _read_js()
    start = js.find("document.body.addEventListener('htmx:beforeRequest'")
    assert start != -1, "htmx:beforeRequest handler must be defined"
    end = js.find("\ndocument.body.addEventListener('htmx:responseError'", start)
    body = js[start:end if end != -1 else len(js)]
    assert "quadlet_type" in body, \
        "the htmx:beforeRequest handler must read quadlet_type from the request parameters"


@pytest.mark.unit
def test_context_menu_start_url_includes_quadlet_type():
    js = _read_js()
    start = js.find("window.showFileContextMenu = function")
    assert start != -1, "showFileContextMenu must be defined"
    end = js.find("\nwindow.", start + 1)
    body = js[start:end if end != -1 else len(js)]
    start_btn_start = body.find("startBtn.onclick")
    assert start_btn_start != -1, "startBtn.onclick must be defined inside showFileContextMenu"
    start_btn_end = body.find("_ctxMenu.appendChild(startBtn)", start_btn_start)
    start_btn_body = body[start_btn_start:start_btn_end if start_btn_end != -1 else len(body)]
    assert "quadlet_type=" in start_btn_body, \
        "the context-menu Start action URL must include quadlet_type="


@pytest.mark.unit
def test_context_menu_stop_url_includes_quadlet_type():
    js = _read_js()
    start = js.find("window.showFileContextMenu = function")
    assert start != -1, "showFileContextMenu must be defined"
    end = js.find("\nwindow.", start + 1)
    body = js[start:end if end != -1 else len(js)]
    stop_btn_start = body.find("stopBtn.onclick")
    assert stop_btn_start != -1, "stopBtn.onclick must be defined inside showFileContextMenu"
    stop_btn_end = body.find("_ctxMenu.appendChild(stopBtn)", stop_btn_start)
    stop_btn_body = body[stop_btn_start:stop_btn_end if stop_btn_end != -1 else len(body)]
    assert "quadlet_type=" in stop_btn_body, \
        "the context-menu Stop action URL must include quadlet_type="


@pytest.mark.unit
def test_editor_pane_systemctl_buttons_include_quadlet_type():
    html = _read_editor_pane()
    assert html.count("quadlet_type=") >= 3, \
        "editor_pane.html's systemctl start/stop/restart button URLs must each include quadlet_type="


@pytest.mark.unit
def test_editor_pane_save_form_has_hidden_quadlet_type_input():
    html = _read_editor_pane()
    form_start = html.find('<form id="save-form"')
    assert form_start != -1, "save-form must be defined"
    form_end = html.find('</form>', form_start)
    form_body = html[form_start:form_end if form_end != -1 else len(html)]
    assert 'name="quadlet_type"' in form_body, \
        "the save form must include a hidden input named quadlet_type"
