import pytest
"""
Tests for active section persistence across page refreshes (Issue #117).
- switchTab must save the active tab to localStorage under 'qm-active-tab'
- DOMContentLoaded must restore from 'qm-active-tab' instead of hard-coding 'overview'
"""
import re

from tests.js_source import read_static_js


def _read():
    return read_static_js()


class TestActiveTabPersistence:
    def setup_method(self):
        self.js = _read()

    @pytest.mark.unit
    def test_switchtab_saves_to_localstorage(self):
        """switchTab must persist the active tab id to localStorage."""
        assert "localStorage.setItem('qm-active-tab'" in self.js, (
            "switchTab must call localStorage.setItem('qm-active-tab', tabId) "
            "to persist the active section."
        )

    @pytest.mark.unit
    def test_domcontentloaded_restores_from_localstorage(self):
        """DOMContentLoaded must restore the active tab from localStorage."""
        assert "localStorage.getItem('qm-active-tab')" in self.js, (
            "DOMContentLoaded must read qm-active-tab from localStorage "
            "to restore the last-viewed section on refresh."
        )

    @pytest.mark.unit
    def test_domcontentloaded_falls_back_to_overview(self):
        """Restoration must fall back to 'overview' if no value is stored."""
        pattern = r"localStorage\.getItem\('qm-active-tab'\)\s*\|\|\s*'overview'"
        assert re.search(pattern, self.js), (
            "switchTab call on DOMContentLoaded must fall back to 'overview' "
            "when no qm-active-tab is stored: localStorage.getItem('qm-active-tab') || 'overview'"
        )

    @pytest.mark.unit
    def test_hardcoded_overview_not_used_on_init(self):
        """DOMContentLoaded must not hard-code switchTab('overview')."""
        assert "switchTab('overview')" not in self.js, (
            "Found switchTab('overview') — replace with "
            "switchTab(localStorage.getItem('qm-active-tab') || 'overview')"
        )
