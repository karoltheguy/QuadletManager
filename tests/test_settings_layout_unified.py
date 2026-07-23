import pytest
"""
Tests for unifying the settings-section layout (Issue #224).

Currently `.settings-group` lays out its children as a responsive
auto-fill grid (`repeat(auto-fill, minmax(340px, 1fr)))`), and individual
`.settings-section` elements can opt out of that grid via a
`.settings-section.full-width` modifier (used throughout
templates/dashboard.html). This produces an inconsistent, multi-column
settings layout with uncapped/centered content widths, and the
add-server-form and admin-root form controls have no max-width cap.

The fix unifies settings sections into a single-column, left-aligned,
flat surface ("flat where it's data, soft where it's chrome"): the
per-section neumorphic cards are removed so sections are grouped by
proximity rather than nested cards, and forms take a reading width so
fields and buttons don't stretch.
- `.settings-group` becomes a single column with a max-width cap instead
  of an auto-fill grid.
- The `.settings-section.full-width` modifier rule is removed since it
  no longer has meaning in a single-column layout.
- The `settings-section full-width` class combination is removed from
  templates/dashboard.html.
- Forms (`.add-server-form`) and admin controls (`#admin-root`) are
  capped to a reading width via max-width.

Covers:
- .settings-group is single-column, capped, and not centered
- .settings-section.full-width rule no longer exists in style.css
- "settings-section full-width" class combo no longer appears in the template
- settings forms / admin controls are capped to a reading width
"""
import os
import re

CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")
TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "dashboard.html"
)


def _css():
    with open(CSS_PATH, encoding="utf-8") as f:
        return f.read()


def _template():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def _extract_rule_block(css, selector_regex):
    """Extract the declaration block `{ ... }` for the first rule whose
    selector matches selector_regex. Returns the block body (without braces)
    or None if not found."""
    m = re.search(selector_regex + r"\s*\{", css)
    if not m:
        return None
    start = m.end()
    end = css.index("}", start)
    return css[start:end]


class TestSettingsGroupSingleColumnCappedLeftAligned:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(self.css, r"\.settings-group")

    @pytest.mark.unit
    def test_settings_group_block_exists(self):
        assert self.block is not None, ".settings-group rule not found"

    @pytest.mark.unit
    def test_settings_group_not_auto_fill_grid(self):
        assert self.block is not None
        assert "auto-fill" not in self.block, (
            ".settings-group should no longer use an auto-fill grid"
        )
        assert "minmax(340px" not in self.block, (
            ".settings-group should no longer use minmax(340px, ...) columns"
        )

    @pytest.mark.unit
    def test_settings_group_has_max_width_cap(self):
        assert self.block is not None
        assert re.search(r"max-width\s*:", self.block) is not None, (
            ".settings-group should declare a max-width content cap"
        )

    @pytest.mark.unit
    def test_settings_group_not_centered(self):
        assert self.block is not None
        assert re.search(r"margin\s*:\s*0\s+auto", self.block) is None, (
            ".settings-group should be left-aligned, not centered via "
            "`margin: 0 auto`"
        )
        assert re.search(r"margin-left\s*:\s*auto", self.block) is None, (
            ".settings-group should be left-aligned, not centered via "
            "`margin-left: auto`"
        )


class TestSettingsSectionFullWidthRuleRemoved:
    def setup_method(self):
        self.css = _css()

    @pytest.mark.unit
    def test_full_width_rule_removed_from_css(self):
        assert re.search(r"\.settings-section\.full-width\s*\{", self.css) is None, (
            ".settings-section.full-width rule should be removed now that "
            "the settings layout is single-column"
        )


class TestFullWidthClassRemovedFromTemplate:
    def setup_method(self):
        self.template = _template()

    @pytest.mark.unit
    def test_full_width_class_combo_not_in_template(self):
        assert "settings-section full-width" not in self.template, (
            "templates/dashboard.html should no longer combine "
            "'settings-section' with 'full-width'"
        )


class TestSettingsFormsCappedToReadingWidth:
    def setup_method(self):
        self.css = _css()

    @pytest.mark.unit
    def test_forms_capped_to_reading_width(self):
        # In the flat surface there are no per-section cards to fill, so the
        # forms themselves take a reading width — fields and buttons don't
        # stretch across the full content column. Durable invariant,
        # independent of the exact width value.
        assert re.search(
            r"\.add-server-form[^{}]*#admin-root[^{}]*\{[^}]*max-width\s*:",
            self.css,
        ) is not None, (
            "Expected settings forms (.add-server-form) and admin controls "
            "(#admin-root) to be capped to a reading width via max-width"
        )
