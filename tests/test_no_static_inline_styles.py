"""
Tests for issue #481: eliminating static inline style attributes from templates
and ensuring required utility classes and CSS rules are defined.
"""
import pathlib
import re

import pytest

from tests.css_source import rule_blocks, strip_comments

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
STATIC_DIR = REPO_ROOT / "static"

DASHBOARD_HTML_PATH = TEMPLATES_DIR / "dashboard.html"
SETTINGS_SERVERS_HTML_PATH = TEMPLATES_DIR / "partials" / "settings_servers.html"
SETTINGS_THEMES_HTML_PATH = TEMPLATES_DIR / "partials" / "settings_themes.html"
SETTINGS_THEMES_PLACEHOLDER_PATH = TEMPLATES_DIR / "partials" / "settings_themes_placeholder.html"
COMPONENTS_CSS_PATH = STATIC_DIR / "components.css"
SETTINGS_CSS_PATH = STATIC_DIR / "settings.css"


def normalize_style_value(val: str) -> str:
    """Normalize inline style attribute value by stripping whitespace and trailing semicolon."""
    cleaned = val.strip().rstrip(";").strip()
    parts = cleaned.split(":", 1)
    if len(parts) == 2:
        prop = " ".join(parts[0].split()).lower()
        val_part = " ".join(parts[1].split()).lower()
        return f"{prop}:{val_part}"
    return " ".join(cleaned.split()).lower()


def parse_css_rules(css_clean: str) -> dict[str, set[str]]:
    """Extract selector -> set of normalized 'property: value' declarations."""
    rules: dict[str, set[str]] = {}
    for block in rule_blocks(css_clean):
        if block.startswith("@"):
            continue
        if "{" not in block:
            continue
        selector_part, _, decl_part = block.partition("{")
        decl_body = decl_part.rstrip("}").strip()
        selectors = [
            " ".join(sel.split())
            for sel in selector_part.split(",")
            if sel.strip()
        ]
        decls = set()
        for decl in decl_body.split(";"):
            decl = decl.strip()
            if not decl or ":" not in decl:
                continue
            prop, val = decl.split(":", 1)
            norm_prop = " ".join(prop.split()).lower()
            norm_val = " ".join(val.split()).lower()
            decls.add(f"{norm_prop}: {norm_val}")

        for sel in selectors:
            rules.setdefault(sel, set()).update(decls)
    return rules


@pytest.mark.unit
def test_theme_placeholder_partial_has_no_inline_styles():
    """Assert templates/partials/settings_themes_placeholder.html contains zero style= attributes."""
    rel_path = SETTINGS_THEMES_PLACEHOLDER_PATH.relative_to(REPO_ROOT).as_posix()
    assert SETTINGS_THEMES_PLACEHOLDER_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = SETTINGS_THEMES_PLACEHOLDER_PATH.read_text(encoding="utf-8")

    offenders = []
    for match in re.finditer(r"<[^>]*\bstyle\s*=\s*([\"'])(.*?)\1[^>]*>", content, re.IGNORECASE):
        tag = " ".join(match.group(0).split())
        offenders.append(tag)

    assert not offenders, (
        f"{rel_path} must contain zero style= attributes, but found {len(offenders)}:\n"
        + "\n".join(f"  - {tag}" for tag in offenders)
    )


@pytest.mark.unit
def test_dashboard_retains_only_display_toggles():
    """Assert templates/dashboard.html retains only style='display:none' attributes."""
    rel_path = DASHBOARD_HTML_PATH.relative_to(REPO_ROOT).as_posix()
    assert DASHBOARD_HTML_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")

    offenders = []
    for match in re.finditer(r"<[^>]*\bstyle\s*=\s*([\"'])(.*?)\1[^>]*>", content, re.IGNORECASE):
        tag = " ".join(match.group(0).split())
        style_val = match.group(2)
        norm = normalize_style_value(style_val)
        if norm != "display:none":
            offenders.append(f'style="{style_val}" in tag: {tag}')

    assert not offenders, (
        f"{rel_path} must only contain style attributes with 'display:none', but found non-conforming:\n"
        + "\n".join(f"  - {item}" for item in offenders)
    )


@pytest.mark.unit
def test_settings_servers_retains_only_display_toggles():
    """Assert templates/partials/settings_servers.html retains only style='display:none' attributes."""
    rel_path = SETTINGS_SERVERS_HTML_PATH.relative_to(REPO_ROOT).as_posix()
    assert SETTINGS_SERVERS_HTML_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = SETTINGS_SERVERS_HTML_PATH.read_text(encoding="utf-8")

    offenders = []
    for match in re.finditer(r"<[^>]*\bstyle\s*=\s*([\"'])(.*?)\1[^>]*>", content, re.IGNORECASE):
        tag = " ".join(match.group(0).split())
        style_val = match.group(2)
        norm = normalize_style_value(style_val)
        if norm != "display:none":
            offenders.append(f'style="{style_val}" in tag: {tag}')

    assert not offenders, (
        f"{rel_path} must only contain style attributes with 'display:none', but found non-conforming:\n"
        + "\n".join(f"  - {item}" for item in offenders)
    )


@pytest.mark.unit
def test_settings_themes_partial_retains_only_dynamic_and_display_styles():
    """Assert templates/partials/settings_themes.html retains only style='display:none'
    and dynamic 'background:' swatch styles.
    """
    rel_path = SETTINGS_THEMES_HTML_PATH.relative_to(REPO_ROOT).as_posix()
    assert SETTINGS_THEMES_HTML_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = SETTINGS_THEMES_HTML_PATH.read_text(encoding="utf-8")

    offenders = []
    for match in re.finditer(r"<[^>]*\bstyle\s*=\s*([\"'])(.*?)\1[^>]*>", content, re.IGNORECASE):
        tag = " ".join(match.group(0).split())
        style_val = match.group(2)
        norm = normalize_style_value(style_val)
        if norm != "display:none" and not norm.startswith("background:"):
            offenders.append(f'style="{style_val}" in tag: {tag}')

    assert not offenders, (
        f"{rel_path} must only contain style attributes that normalize to 'display:none' "
        f"or start with 'background:', but found non-conforming:\n"
        + "\n".join(f"  - {item}" for item in offenders)
    )


@pytest.mark.unit
def test_spacing_utilities_are_defined():
    """Assert static/components.css defines utility classes .mb-0, .pt-0, .px-0, and .gap-2
    with exact declarations.
    """
    rel_path = COMPONENTS_CSS_PATH.relative_to(REPO_ROOT).as_posix()
    assert COMPONENTS_CSS_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = COMPONENTS_CSS_PATH.read_text(encoding="utf-8")
    css_clean = strip_comments(content)
    rules = parse_css_rules(css_clean)

    required_utilities = {
        ".mb-0": {"margin-bottom: 0"},
        ".gap-2": {"gap: 0.5rem"},
    }

    missing = []
    for selector, required_decls in required_utilities.items():
        declared = rules.get(selector, set())
        missing_decls = required_decls - declared
        if missing_decls:
            missing.append(f"{selector} (missing declarations: {sorted(missing_decls)})")

    assert not missing, (
        f"{rel_path} must define the required spacing utility classes with exact declarations. Missing:\n"
        + "\n".join(f"  - {entry}" for entry in missing)
    )


@pytest.mark.unit
def test_actions_column_keeps_nowrap():
    """Assert static/settings.css applies 'white-space: nowrap' to '.settings-table td.actions-col'."""
    rel_path = SETTINGS_CSS_PATH.relative_to(REPO_ROOT).as_posix()
    assert SETTINGS_CSS_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = SETTINGS_CSS_PATH.read_text(encoding="utf-8")
    css_clean = strip_comments(content)
    rules = parse_css_rules(css_clean)

    target_selector = ".settings-table td.actions-col"
    declared = rules.get(target_selector, set())

    assert "white-space: nowrap" in declared, (
        f"{rel_path} must define 'white-space: nowrap' for selector '{target_selector}'. "
        f"Found declarations for {target_selector}: {sorted(declared)}"
    )


@pytest.mark.unit
def test_new_utilities_outrank_the_component_rules_they_override():
    """.mb-0 and .gap-2 must be declared after .form-label and .form-row.

    Equal specificity means source order decides. The inline styles these
    replace won because inline beats classes; a utility declared earlier in the
    file would silently lose and change the rendering.
    """
    rel_path = COMPONENTS_CSS_PATH.relative_to(REPO_ROOT).as_posix()
    css = strip_comments(COMPONENTS_CSS_PATH.read_text(encoding="utf-8"))

    def position(selector: str) -> int:
        match = re.search(rf"(^|[}}\s]){re.escape(selector)}\s*[,{{]", css)
        return match.start() if match else -1

    problems = []
    for utility, component in ((".mb-0", ".form-label"), (".gap-2", ".form-row")):
        util_at, comp_at = position(utility), position(component)
        if util_at < 0:
            problems.append(f"{utility} is not defined in {rel_path}")
        elif comp_at >= 0 and util_at < comp_at:
            problems.append(
                f"{utility} (offset {util_at}) is declared before {component} "
                f"(offset {comp_at}), so {component} wins and the utility has no effect"
            )

    assert not problems, "\n".join(f"  - {p}" for p in problems)
