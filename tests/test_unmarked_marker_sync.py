"""The `unmarked` marker expression is duplicated, so pin the copies together.

It appears in three places:

* `.github/workflows/tests.yml`, twice, once per matrix block.
* `tests/conftest.py` as UNMARKED_MARKEXPR, where `pytest_sessionfinish`
  compares it by **string equality** to turn pytest's exit-5 ("no tests
  collected") into a pass.

Because that comparison is exact, changing the workflow without changing the
conftest does not fail loudly. The conversion just stops happening, and the
`unmarked` job goes red the first time the expression selects nothing. This
test is what makes that drift a failure instead.

It is also how the podman suite gets excluded: without `and not podman` the
`unmarked` job collects tests that need a live podman host it does not have.
"""

import os
import re

import pytest

from tests.conftest import UNMARKED_MARKEXPR


def _workflow_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, ".github", "workflows", "tests.yml")


def _unmarked_markers():
    """Every `marker:` value belonging to a `suite: unmarked` matrix entry."""
    with open(_workflow_path(), "r", encoding="utf-8") as handle:
        text = handle.read()
    return re.findall(
        r"- suite:\s*unmarked\s*\n\s*marker:\s*\"([^\"]+)\"", text
    )


@pytest.mark.unit
def test_workflow_defines_two_unmarked_suites():
    """One per matrix block. If this changes, the assertions below are stale."""
    markers = _unmarked_markers()
    assert len(markers) == 2, (
        f"expected an `unmarked` suite in both matrix blocks, found {len(markers)}: {markers}"
    )


@pytest.mark.unit
def test_unmarked_marker_matches_conftest_constant():
    for marker in _unmarked_markers():
        assert marker == UNMARKED_MARKEXPR, (
            "the `unmarked` marker in .github/workflows/tests.yml has drifted "
            f"from tests/conftest.py's UNMARKED_MARKEXPR.\n"
            f"  workflow: {marker!r}\n"
            f"  conftest: {UNMARKED_MARKEXPR!r}\n"
            "pytest_sessionfinish compares these by string equality, so the "
            "exit-5 conversion silently stops working when they differ."
        )


@pytest.mark.unit
def test_unmarked_marker_excludes_the_podman_suite():
    """The podman tests need a live Podman 5 host over SSH. The `unmarked` job
    has none, so collecting them there is a guaranteed failure."""
    assert "not podman" in UNMARKED_MARKEXPR
    for marker in _unmarked_markers():
        assert "not podman" in marker, (
            f"{marker!r} would collect the podman suite on a runner with no podman host"
        )
