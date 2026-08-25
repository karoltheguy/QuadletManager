/**
 * Shared mutable frontend state touched by three or more concern clusters.
 * Centralized here so state ownership does not depend on which module is extracted next.
 */

// ── Shared Collections ─────────────────────────────────────
export const lastStatsPerServer = {};
export const runningContainersBySid = {};
export const manualStops = new Set(); // tracks serverId:stem that we intentionally stopped
export const pendingStarts = {}; // tracks stems waiting for active status
export const chartColorByName = new Map();
export const monitorChartSelection = new Set();
export const _terminalTabs = new Map();   // tabKey → { term, ws, fitAddon, tabEl, paneEl }
export const _logTabs = new Map();   // tabKey → { ws, logDiv, tabEl, paneEl, serverId, unitName, scope }

// ── Shared Reassignable Scalars ────────────────────────────
export const state = {
    activeServerId: null,
    monitorContainerFilter: '',
    _selectedContainerStem: null,
    _selectedContainerServerId: null,
    _selectedContainerScope: null,
    _selectedContainerType: null,
    _quadletRestored: false,
    _monitoringServerId: null,
    _monitorChartMinutes: 60,
    cpuHistoryChart: null,
    memHistoryChart: null,
    _activeTerminalTabKey: null,
    _activeLogTabKey: null,
};
