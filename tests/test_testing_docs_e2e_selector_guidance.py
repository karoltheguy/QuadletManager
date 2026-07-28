import os
import re

import pytest

SECTION_HEADING = "### Selecting elements in E2E tests"
HAZARD_SELECTOR = "#settings-pane .btn-primary"

# Matches repo-relative test paths under tests/e2e/, optionally wrapped in
# markdown backticks, e.g. "`tests/e2e/test_settings_layout.py`".
_E2E_PATH_RE = re.compile(r"`?(tests/e2e/[\w\-/]+\.py)`?")


def _testing_docs_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "docs", "TESTING.md")


def _load_testing_docs():
    path = _testing_docs_path()
    assert os.path.isfile(path), f"{path} is missing"
    with open(path, "r") as f:
        return f.read()


def _extract_section_body(content, heading):
    """Return the text between `heading` and the next '###' or '##' heading
    (or end of file), not including the heading line itself. Returns None if
    `heading` is not present in `content`."""
    start = content.find(heading)
    if start == -1:
        return None
    after_heading = start + len(heading)
    next_heading_match = re.search(
        r"^##+\s", content[after_heading:], re.MULTILINE
    )
    if next_heading_match:
        end = after_heading + next_heading_match.start()
    else:
        end = len(content)
    return content[after_heading:end]


def _extract_e2e_test_paths(section_body):
    return _E2E_PATH_RE.findall(section_body)


@pytest.mark.unit
def test_testing_docs_has_selecting_elements_in_e2e_tests_heading():
    """Verify docs/TESTING.md contains a '### Selecting elements in E2E
    tests' heading, documenting the selector-ambiguity hazard from #234."""
    content = _load_testing_docs()
    assert SECTION_HEADING in content, (
        f"docs/TESTING.md does not contain the heading {SECTION_HEADING!r}; "
        f"expected a section documenting the E2E selector hazard from #234"
    )


@pytest.mark.unit
def test_selecting_elements_section_names_the_ambiguous_selector():
    """Verify the 'Selecting elements in E2E tests' section body names the
    exact hazardous selector '#settings-pane .btn-primary' (see #234), so
    the guidance names the concrete trap rather than speaking abstractly."""
    content = _load_testing_docs()
    section_body = _extract_section_body(content, SECTION_HEADING)
    assert section_body is not None, (
        f"docs/TESTING.md does not contain the heading {SECTION_HEADING!r}, "
        f"so the hazardous selector {HAZARD_SELECTOR!r} cannot be verified"
    )
    assert HAZARD_SELECTOR in section_body, (
        f"'Selecting elements in E2E tests' section body does not contain "
        f"{HAZARD_SELECTOR!r}; found body: {section_body!r}"
    )


@pytest.mark.unit
def test_selecting_elements_section_cites_an_existing_example_test_file():
    """Verify the 'Selecting elements in E2E tests' section cites at least
    one repo-relative tests/e2e/*.py example, and that every path it cites
    still exists on disk. This guards against doc rot: if the example test
    is later renamed or deleted, this test must fail (see #234)."""
    content = _load_testing_docs()
    section_body = _extract_section_body(content, SECTION_HEADING)
    assert section_body is not None, (
        f"docs/TESTING.md does not contain the heading {SECTION_HEADING!r}, "
        f"so no example test file citation can be verified"
    )

    paths = _extract_e2e_test_paths(section_body)
    assert len(paths) > 0, (
        "'Selecting elements in E2E tests' section cites no example test "
        "file matching tests/e2e/<something>.py"
    )

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    missing = [
        p for p in paths if not os.path.isfile(os.path.join(base_dir, p))
    ]
    assert not missing, (
        f"'Selecting elements in E2E tests' section cites path(s) that do "
        f"not exist on disk: {missing!r}"
    )
