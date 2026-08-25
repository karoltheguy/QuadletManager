import pytest
"""
Tests for UI selection persistence across page refreshes (Issue #118).
Covers:
- Bottom panel tab (terminal/logs) persisted to qm-bottom-tab
- Monitor server selection persisted to qm-monitor-server
- Selected quadlet persisted to qm-selected-quadlet and restored via htmx:afterSwap
"""
import re

from tests.js_source import read_static_js


def _read():
    return read_static_js()


class TestBottomPanelTabPersistence:
    def setup_method(self):
        self.js = _read()

    @pytest.mark.unit
    def test_switch_bottom_tab_saves_to_localstorage(self):
        assert "localStorage.setItem('qm-bottom-tab', pane)" in self.js, (
            "switchBottomTab must persist the active pane to localStorage "
            "under 'qm-bottom-tab'."
        )

    @pytest.mark.unit
    def test_domcontentloaded_restores_bottom_tab(self):
        assert "localStorage.getItem('qm-bottom-tab')" in self.js, (
            "DOMContentLoaded must read 'qm-bottom-tab' from localStorage "
            "to restore the last active bottom panel tab."
        )

    @pytest.mark.unit
    def test_domcontentloaded_bottom_tab_falls_back_to_terminal(self):
        pattern = r"localStorage\.getItem\('qm-bottom-tab'\)\s*\|\|\s*'terminal'"
        assert re.search(pattern, self.js), (
            "switchBottomTab call on DOMContentLoaded must fall back to "
            "'terminal' when no qm-bottom-tab is stored."
        )


class TestMonitorServerPersistence:
    def setup_method(self):
        self.js = _read()

    @pytest.mark.unit
    def test_select_monitoring_server_saves_to_localstorage(self):
        assert "localStorage.setItem('qm-monitor-server'" in self.js, (
            "selectMonitoringServer must persist the selected server id to "
            "localStorage under 'qm-monitor-server'."
        )

    @pytest.mark.unit
    def test_restore_monitoring_selection_reads_saved_server(self):
        assert "localStorage.getItem('qm-monitor-server')" in self.js, (
            "restoreMonitoringServerSelection must read 'qm-monitor-server' "
            "from localStorage and auto-select it once the option exists."
        )

    @pytest.mark.unit
    def test_restore_only_when_no_server_selected(self):
        # The guard must check _monitoringServerId before auto-restoring.
        assert "_monitoringServerId" in self.js, (
            "Monitor server restore must be guarded by _monitoringServerId "
            "so it only fires before the user makes a selection."
        )


class TestQuadletSelectionPersistence:
    def setup_method(self):
        self.js = _read()

    @pytest.mark.unit
    def test_select_container_stem_saves_to_localstorage(self):
        assert "localStorage.setItem('qm-selected-quadlet'" in self.js, (
            "selectContainerStem must persist stem/serverId/scope to "
            "localStorage under 'qm-selected-quadlet'."
        )

    @pytest.mark.unit
    def test_restore_quadlet_selection_function_exists(self):
        assert "restoreQuadletSelection" in self.js, (
            "A restoreQuadletSelection function must exist to restore the "
            "saved quadlet after the HTMX tree loads."
        )

    @pytest.mark.unit
    def test_restore_guarded_by_quadlet_restored_flag(self):
        assert "_quadletRestored" in self.js, (
            "restoreQuadletSelection must use a _quadletRestored flag to "
            "prevent overriding user selections on subsequent tree re-renders."
        )

    @pytest.mark.unit
    def test_restore_called_from_htmx_after_swap(self):
        # Check that restoreQuadletSelection is called inside htmx:afterSwap
        pattern = r"htmx:afterSwap[\s\S]{0,500}restoreQuadletSelection"
        assert re.search(pattern, self.js), (
            "restoreQuadletSelection must be called from the htmx:afterSwap "
            "handler, since the quadlet tree is loaded via HTMX, not inline."
        )

    @pytest.mark.unit
    def test_restore_reads_localstorage(self):
        assert "localStorage.getItem('qm-selected-quadlet')" in self.js, (
            "restoreQuadletSelection must read 'qm-selected-quadlet' from "
            "localStorage to find the previously selected quadlet."
        )
