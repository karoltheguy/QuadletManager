import os
import re

import pytest


def _testing_md_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "docs", "TESTING.md")


def _theme_on_primary_contrast_e2e_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(
        base_dir, "tests", "e2e", "test_theme_on_primary_contrast_e2e.py"
    )


def _read_file(path):
    assert os.path.isfile(path), f"{path} is missing"
    with open(path, "r") as f:
        return f.read()


def _extract_selecting_elements_section(markdown_text):
    """Extract the body of the '### Selecting elements in E2E tests' section,
    from its heading up to (but not including) the next '##' or '###'
    heading, or EOF if there is none."""
    lines = markdown_text.splitlines()
    start_index = None
    for i, line in enumerate(lines):
        if line.strip() == "### Selecting elements in E2E tests":
            start_index = i
            break

    assert start_index is not None, (
        "docs/TESTING.md is missing the "
        "'### Selecting elements in E2E tests' heading"
    )

    end_index = len(lines)
    for j in range(start_index + 1, len(lines)):
        if re.match(r"^#{2,3}\s", lines[j]):
            end_index = j
            break

    return "\n".join(lines[start_index:end_index])


@pytest.mark.unit
def test_testing_md_selecting_elements_section_prescribes_role_based_locators():
    """Verify docs/TESTING.md's '### Selecting elements in E2E tests' section
    prescribes role-based locators (get_by_role) as the fix for the
    ambiguous '#settings-pane .btn-primary' hazard, not just container
    scoping (see #234)."""
    text = _read_file(_testing_md_path())
    section = _extract_selecting_elements_section(text)
    assert "get_by_role" in section, (
        "'### Selecting elements in E2E tests' section of docs/TESTING.md "
        f"does not mention 'get_by_role'; section body found was:\n{section}"
    )


@pytest.mark.unit
def test_theme_on_primary_contrast_e2e_uses_get_by_role_for_settings_primary_button():
    """Verify tests/e2e/test_theme_on_primary_contrast_e2e.py locates the
    settings primary button via a role-based locator (get_by_role), rather
    than the ambiguous '#settings-pane .btn-primary' CSS-class selector
    (see #234)."""
    path = _theme_on_primary_contrast_e2e_path()
    source = _read_file(path)
    assert "get_by_role" in source, (
        f"{path} does not contain 'get_by_role'; it should locate the "
        "settings primary button via a role-based locator instead of a "
        "CSS-class selector"
    )
