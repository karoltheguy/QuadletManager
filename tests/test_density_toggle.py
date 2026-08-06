import pytest
"""
Tests for UI Density toggle (Issue #109).
- dashboard.html must have the density section with Relaxed/Compact radio buttons
- style.css must define --density-* tokens and [data-density="compact"] overrides
- FOUC-prevention: dashboard.html head must apply qm-density from localStorage
"""
import os
import re

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")
CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestDensityHTML:
    def setup_method(self):
        self.html = _read(TEMPLATE_PATH)

    @pytest.mark.unit
    def test_density_section_exists(self):
        assert 'id="density-section"' in self.html, "density-section div must be present"

    @pytest.mark.unit
    def test_density_relaxed_radio_exists(self):
        assert 'id="density-relaxed"' in self.html, "density-relaxed radio input must be present"

    @pytest.mark.unit
    def test_density_compact_radio_exists(self):
        assert 'id="density-compact"' in self.html, "density-compact radio input must be present"

    @pytest.mark.unit
    def test_density_toggle_calls_js(self):
        assert "toggleDensity('relaxed')" in self.html
        assert "toggleDensity('compact')" in self.html

    @pytest.mark.unit
    def test_density_section_is_outside_themes_root(self):
        themes_root_start = self.html.find('<div id="themes-root"')
        density_section_pos = self.html.find('id="density-section"')
        assert themes_root_start != -1
        assert density_section_pos != -1
        themes_root_end = self.html.find('</div>', themes_root_start)
        assert density_section_pos > themes_root_end, (
            "density-section must be outside #themes-root to survive htmx swaps"
        )

    @pytest.mark.unit
    def test_fouc_prevention_in_head(self):
        head_end = self.html.find('</head>')
        head = self.html[:head_end]
        assert 'qm-density' in head, "FOUC-prevention script must read qm-density in <head>"
        assert "data-density" in head or "dataset.density" in head, (
            "FOUC-prevention script must set data-density on <html>"
        )


class TestDensityCSS:
    def setup_method(self):
        self.css = _read(CSS_PATH)

    @pytest.mark.unit
    def test_density_panel_padding_token_defined(self):
        assert '--density-panel-padding' in self.css

    @pytest.mark.unit
    def test_density_gap_token_defined(self):
        assert '--density-gap' in self.css

    @pytest.mark.unit
    def test_density_section_padding_token_defined(self):
        assert '--density-section-padding' in self.css

    @pytest.mark.unit
    def test_compact_override_block_exists(self):
        assert '[data-density="compact"]' in self.css

    @pytest.mark.unit
    def test_compact_reduces_panel_padding(self):
        compact_block_match = re.search(
            r'\[data-density="compact"\]\s*\{([^}]+)\}', self.css
        )
        assert compact_block_match, "[data-density='compact'] block not found"
        block = compact_block_match.group(1)
        assert '--density-panel-padding' in block

    @pytest.mark.unit
    def test_settings_main_uses_density_token(self):
        assert 'padding: var(--density-panel-padding)' in self.css

    @pytest.mark.unit
    def test_settings_group_uses_density_gap_token(self):
        assert 'gap: var(--density-gap)' in self.css

    @pytest.mark.unit
    def test_settings_section_separation_is_density_aware(self):
        # The settings surface was flattened (issue #224): sections are no
        # longer per-section cards with `--density-section-padding`, so
        # density now drives their separation through the flat-section
        # divider. Density must still tighten/loosen settings.
        divider = re.search(
            r'\.settings-section \+ \.settings-section\s*\{([^}]+)\}', self.css
        )
        assert divider, ".settings-section divider rule not found"
        assert 'var(--density-' in divider.group(1), (
            "flat settings sections must be separated by a density-aware amount"
        )

    @pytest.mark.unit
    def test_raised_panels_use_density_token(self):
        assert 'padding: var(--density-panel-padding)' in self.css
