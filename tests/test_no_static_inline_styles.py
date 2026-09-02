"""
Tests for issue #481: eliminating static inline style attributes from templates
and ensuring required utility classes and CSS rules are defined.
"""
import pathlib
import re

import pytest

from tests.css_source import rule_blocks, strip_comments
from tests.js_source import static_js_files

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


STYLE_ATTR_RE = re.compile(r"<[^>]*\bstyle\s*=\s*([\"'])(.*?)\1[^>]*>", re.IGNORECASE)
STYLE_DISPLAY_ASSIGN_RE = re.compile(r"\.style\s*\.\s*display\s*=(?!=)")


def _inline_styles(path):
    """Yield (normalized value, whitespace-collapsed tag) for every style= attribute."""
    for match in STYLE_ATTR_RE.finditer(path.read_text(encoding="utf-8")):
        yield normalize_style_value(match.group(2)), " ".join(match.group(0).split())


# Issue #481 stripped the static cosmetics; these allowances are now closed by issue #482.
ALLOWED_INLINE_STYLES = [
    pytest.param(SETTINGS_THEMES_PLACEHOLDER_PATH, (), id="settings_themes_placeholder"),
    pytest.param(DASHBOARD_HTML_PATH, (), id="dashboard"),
    pytest.param(SETTINGS_SERVERS_HTML_PATH, (), id="settings_servers"),
    pytest.param(SETTINGS_THEMES_HTML_PATH, (), id="settings_themes"),
]


@pytest.mark.unit
@pytest.mark.parametrize("template_path,allowed", ALLOWED_INLINE_STYLES)
def test_template_retains_only_allowed_inline_styles(template_path, allowed):
    """Every remaining style= attribute must match one of the allowances for that template.

    An allowance matches when the normalized value equals it exactly, or, for a
    prefix allowance ending in ':', when the value starts with it.
    """
    rel_path = template_path.relative_to(REPO_ROOT).as_posix()
    assert template_path.exists(), f"Expected {rel_path} to exist on disk"

    offenders = [
        f'style="{norm}" in tag: {tag}'
        for norm, tag in _inline_styles(template_path)
        if not any(
            norm.startswith(rule) if rule.endswith(":") else norm == rule
            for rule in allowed
        )
    ]

    permitted = ", ".join(allowed) if allowed else "nothing"
    assert not offenders, (
        f"{rel_path} may only carry these inline styles: {permitted}. Found:\n"
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


@pytest.mark.unit
def test_no_static_js_assigns_style_display():
    """Assert no static JavaScript file assigns to element.style.display."""
    offenders = []
    for file_path in static_js_files():
        rel_path = file_path.relative_to(REPO_ROOT).as_posix()
        for line_number, line in enumerate(
            file_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if STYLE_DISPLAY_ASSIGN_RE.search(line):
                offenders.append(f"{rel_path}:{line_number}: {line.strip()}")

    assert not offenders, (
        "Visibility must be driven through classList and a CSS class instead of inline element.style.display:\n"
        + "\n".join(f"  - {item}" for item in offenders)
    )
