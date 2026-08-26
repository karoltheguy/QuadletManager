"""Data-gated browser tests must not be able to report green having never run.

Seven tests in tests/e2e/test_status_dots.py and tests/e2e/test_stats_e2e.py
call `pytest.skip` inside the test body when the quadlet sidebar is empty
(no servers, no quadlet files, no `.container` file). The CI `unmarked`
job that collects them never has that data, so every one of the seven
skips unconditionally and the job goes green having exercised nothing.

The fix moves those seven tests onto the `podman` marker (which the
`unmarked` job excludes, see tests/test_unmarked_marker_sync.py) and
removes their in-body `pytest.skip` calls, following the precedent of
tests/e2e/test_podman_e2e.py. `test_stats_update_received` in
test_stats_e2e.py only needs a seeded server row, so it stays on `e2e`.

This guard asserts that state directly from the source, via `ast`, so a
future regression that reintroduces a data-dependent skip or puts one of
these tests back on `e2e` fails loudly instead of quietly going green.
"""
import ast
import os

import pytest

STATUS_DOTS_TEST_NAMES = {
    "test_status_dots_present_after_tree_loads",
    "test_status_dots_start_as_stopped",
    "test_dot_transitions_to_running_on_stats_update",
    "test_dot_returns_to_stopped_when_container_disappears",
    "test_multiple_servers_dots_update_independently",
    "test_dot_title_attribute_reflects_state",
}


def _status_dots_path():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "e2e", "test_status_dots.py")


def _stats_e2e_path():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "e2e", "test_stats_e2e.py")


def _read_source(path):
    assert os.path.isfile(path), f"{path} is missing"
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _parse(path):
    return ast.parse(_read_source(path), filename=path)


def _mark_names(decorator_list):
    """Names of `pytest.mark.<name>` decorators/expressions in a list."""
    names = set()
    for node in decorator_list:
        target = node.func if isinstance(node, ast.Call) else node
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _module_pytestmark_node(tree):
    """The RHS of the module-level `pytestmark = ...` assignment, or None."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    return node.value
    return None


def _module_pytestmark_elements(tree):
    """`pytestmark` as a list of expressions, whether or not it is a list."""
    value = _module_pytestmark_node(tree)
    if value is None:
        return []
    if isinstance(value, ast.List):
        return list(value.elts)
    return [value]


def _skip_calls_in(node):
    """All `pytest.skip(...)` Call nodes found anywhere inside `node`."""
    calls = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "skip"
            and isinstance(func.value, ast.Name)
            and func.value.id == "pytest"
        ):
            calls.append(sub)
    return calls


def _test_functions(tree):
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def _function_by_name(tree, name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


@pytest.mark.unit
def test_status_dots_module_declares_podman_marker_and_drops_e2e_decorators():
    """test_status_dots.py needs the whole module on `podman`, not `e2e`.

    All six tests here skip when the sidebar has no quadlet files, which
    the `unmarked` job's environment guarantees, so they must move off
    `e2e` (which the `unmarked` job collects) onto `podman` (which it
    excludes).
    """
    path = _status_dots_path()
    tree = _parse(path)

    pytestmark_names = _mark_names(_module_pytestmark_elements(tree))
    assert "podman" in pytestmark_names, (
        f"{path}: module-level `pytestmark` does not include "
        "`pytest.mark.podman`; the data-dependent tests here need to run "
        "only in the podman suite, following tests/e2e/test_podman_e2e.py"
    )

    for func in _test_functions(tree):
        decorator_names = _mark_names(func.decorator_list)
        assert "e2e" not in decorator_names, (
            f"{path}: {func.name} still carries @pytest.mark.e2e; it must "
            "rely solely on the module-level podman marker"
        )


@pytest.mark.unit
def test_stats_e2e_functions_carry_the_correct_marker_each():
    """Only `test_log_streaming_ui` is data-dependent; `test_stats_update_received`
    stays on `e2e` because it only needs a seeded server row."""
    path = _stats_e2e_path()
    tree = _parse(path)

    log_streaming = _function_by_name(tree, "test_log_streaming_ui")
    assert log_streaming is not None, f"{path}: test_log_streaming_ui not found"
    log_streaming_marks = _mark_names(log_streaming.decorator_list)
    assert "podman" in log_streaming_marks, (
        f"{path}: test_log_streaming_ui is not marked `podman`; it skips "
        "when no `.container` file is in the sidebar, which the `unmarked` "
        "job's environment guarantees, so it must run only in the podman suite"
    )
    assert "e2e" not in log_streaming_marks, (
        f"{path}: test_log_streaming_ui is still marked `e2e`; the "
        "`unmarked` job collects `e2e` tests and would skip it every time"
    )

    stats_update = _function_by_name(tree, "test_stats_update_received")
    assert stats_update is not None, f"{path}: test_stats_update_received not found"
    stats_update_marks = _mark_names(stats_update.decorator_list)
    assert "e2e" in stats_update_marks, (
        f"{path}: test_stats_update_received lost its @pytest.mark.e2e; it "
        "only needs a seeded server row, not live quadlet data, so it "
        "should remain in the `e2e` suite"
    )


@pytest.mark.unit
def test_status_dots_and_stats_e2e_have_no_data_gated_skips():
    """No function in this module may call pytest.skip; use
    skip_unless_seeded for the one legitimate environmental gate.

    This walks every `ast.FunctionDef` in each module, test functions,
    fixtures, and module-level helpers alike, so no function name is
    hardcoded here and none of them can quietly reintroduce a data-gated
    skip."""
    for path in (_status_dots_path(), _stats_e2e_path()):
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            skip_calls = _skip_calls_in(node)
            assert not skip_calls, (
                f"{path}: {node.name} still calls pytest.skip(...) at line "
                f"{skip_calls[0].lineno}; no function in this module may "
                "call pytest.skip; use skip_unless_seeded for the one "
                "legitimate environmental gate"
            )
