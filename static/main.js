/* global htmx, Chart, Terminal, healthHistoryChart, monitoringChart, require */
import { lastStatsPerServer, runningContainersBySid, manualStops,
         pendingStarts, chartColorByName, monitorChartSelection,
         _terminalTabs, _logTabs, state } from '@qm/state';
import { el, sendNotification, getRelativeTime, setStatText } from '@qm/dom';
import { onPrimaryFor, hexToRgba } from '@qm/color';

// ── Server Collapse ───────────────────────────────────────
function toggleServerCollapse(serverId) {
    const li = document.querySelector('li[data-server-id="' + serverId + '"]');
    if (!li) return;
    const collapsed = li.classList.toggle('is-collapsed');
    const btn = li.querySelector('.server-row-toggle');
    if (btn) btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    try {
        localStorage.setItem('qm-server-collapsed-' + serverId, collapsed ? '1' : '0');
    } catch {
        // Ignore localStorage restrictions
    }
}

function restoreServerCollapseStates() {
    document.querySelectorAll('li[data-server-id]').forEach(function(li) {
        const id = li.dataset.serverId;
        let saved;
        try {
            saved = localStorage.getItem('qm-server-collapsed-' + id);
        } catch {
            // Ignore localStorage restrictions
        }
        if (saved === '1') {
            li.classList.add('is-collapsed');
            const btn = li.querySelector('.server-row-toggle');
            if (btn) btn.setAttribute('aria-expanded', 'false');
        }
    });
}

function handleServerCollapseKey(e, li, sid) {
    const key = e.key;
    const isCollapsed = li.classList.contains('is-collapsed');
    // Left collapses an expanded server, Right expands a collapsed one, and
    // Enter/Space toggles either way. All three end in the same toggle.
    const shouldToggle = (key === 'ArrowLeft' && !isCollapsed)
        || (key === 'ArrowRight' && isCollapsed)
        || key === 'Enter'
        || key === ' ';
    if (shouldToggle) {
        e.preventDefault();
        window.toggleServerCollapse(sid);
    }
}

function handleGlobalKeydown(e) {
    const toggle = e.target.closest('.server-row-toggle');
    if (!toggle) return;
    const li = toggle.closest('li[data-server-id]');
    if (!li) return;
    handleServerCollapseKey(e, li, li.dataset.serverId);
}
document.addEventListener('keydown', handleGlobalKeydown);

// ── Profile Menu ─────────────────────────────────────────
function toggleProfileMenu() {
    const menu = document.getElementById('profile-menu');
    menu.hidden = !menu.hidden;
}

// Both this listener and the delegated dispatch below are registered on
// document, so stopPropagation in a button handler cannot stop this one;
// listener registration order does not help either. Excluding clicks that
// land on #profile-btn is what lets the click that opens the menu survive
// instead of being immediately undone by this listener.
document.addEventListener('click', function(e) {
    if (e.target.closest('#profile-btn')) return;
    const menu = document.getElementById('profile-menu');
    if (menu) menu.hidden = true;
});

// ── Theme Toggle ─────────────────────────────────────────
// No saved pref → follows OS via CSS @media (prefers-color-scheme).
// First click reads the currently-resolved theme and flips to the
// opposite, then persists to localStorage so the override sticks.
function toggleTheme() {
    const root = document.documentElement;
    let current = root.dataset.theme;
    if (!current) {
        current = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    const next = current === 'light' ? 'dark' : 'light';
    root.dataset.theme = next;
    try {
        localStorage.setItem('qm-theme-override', next);
    } catch {
        // Ignore localStorage restrictions
    }
    applyChartTheme();
    applyEditorTheme();
}

// ── Density Toggle ───────────────────────────────────────
function toggleDensity(value) {
    const root = document.documentElement;
    if (value === 'compact') {
        root.dataset.density = 'compact';
    } else {
        delete root.dataset.density;
    }
    try {
        localStorage.setItem('qm-density', value);
    } catch {
        // Ignore localStorage restrictions
    }
}

function initDensityRadio() {
    let stored = 'relaxed';
    try {
        stored = localStorage.getItem('qm-density') || 'relaxed';
    } catch {
        // Ignore localStorage restrictions
    }
    const radio = document.getElementById('density-' + stored);
    if (radio) radio.checked = true;
}

// ── Editor Theme Toggle ──────────────────────────────────
function toggleEditorTheme(value) {
    try {
        localStorage.setItem('qm-editor-theme', value);
    } catch {
        // Ignore localStorage restrictions
    }
    applyEditorTheme();
}

function initEditorThemeRadio() {
    let stored = 'follow';
    try {
        stored = localStorage.getItem('qm-editor-theme') || 'follow';
    } catch {
        // Ignore localStorage restrictions
    }
    const radio = document.getElementById('editor-theme-' + stored);
    if (radio) radio.checked = true;
}

// ── Theme Preview ─────────────────────────────────────────

// NOTE: load_active_theme() in api/routes.py only injects --brand-on-primary
// when a saved theme has a custom brand_primary override; the live preview
// below always emits it. This is not a divergence -- onPrimaryFor() reproduces
// the static CSS defaults for both shipped brand colors (#14b8a6 -> #1c1f24,
// #0e7268 -> #ffffff), so emitting it unconditionally here matches what the
// server would compute either way.
function applyThemePreview(form) {
    const mode = form.dataset.mode;
    let rules = '';
    let brandPrimary = null;
    form.querySelectorAll('input[type="color"][name]').forEach(function(inp) {
        rules += '--' + inp.name.replaceAll('_', '-') + ':' + inp.value + ';';
        if (inp.name === 'brand_primary') brandPrimary = inp.value;
    });
    if (brandPrimary) {
        rules += '--brand-on-primary:' + onPrimaryFor(brandPrimary) + ';';
    }
    const css = ':root[data-theme="' + mode + '"]{' + rules + '}';
    let el = document.getElementById('qm-theme-preview');
    if (!el) {
        el = document.createElement('style');
        el.id = 'qm-theme-preview';
        const anchor = document.getElementById('qm-theme-overrides');
        if (anchor) anchor.after(el);
        else document.head.appendChild(el);
    }
    el.textContent = css;
}

function clearThemePreview() {
    const el = document.getElementById('qm-theme-preview');
    if (el) el.remove();
}

// ── Hex ⇄ Color-picker sync (event delegation on #themes-root) ───────────────
document.addEventListener('change', function(e) {
    if (e.target.type === 'color' && e.target.dataset.hexId) {
        const txt = document.getElementById(e.target.dataset.hexId);
        if (txt) txt.value = e.target.value;
    }
});
function handleGlobalInput(e) {
    if (!e.target.classList.contains('hex-input')) return;
    const val = e.target.value;
    if (/^#[0-9a-fA-F]{6}$/.test(val)) {
        e.target.style.outline = '';
        const picker = document.querySelector('input[type="color"][data-hex-id="' + e.target.id + '"]');
        if (picker) picker.value = val;
    } else {
        e.target.style.outline = '2px solid red';
    }
}
document.addEventListener('input', handleGlobalInput);

// ── Theme-updated HTMX trigger ────────────────────────────────────────────────
document.body.addEventListener('theme-updated', function() {
    clearThemePreview();
    applyChartTheme();
    applyEditorTheme();
});

// Mirrors services/quadlet_naming.py. Podman's generator suffixes
// pod/volume/network/image/build units with their type; container and
// kube units are unsuffixed.
const SUFFIXED_QUADLET_TYPES = new Set(['pod', 'volume', 'network', 'image', 'build']);

function unitNameFor(fileName) {
    const dotIndex = fileName.lastIndexOf('.');
    if (dotIndex === -1) return fileName + '.service';
    const base = fileName.slice(0, dotIndex);
    const type = fileName.slice(dotIndex + 1).toLowerCase();
    if (SUFFIXED_QUADLET_TYPES.has(type)) return base + '-' + type + '.service';
    return base + '.service';
}

// Podman's generator maps both `my.pod` and `my-pod.container` to the same
// unit name `my-pod.service`, so stripping a `-<type>` suffix by guessing
// from the unit name alone is ambiguous. The caller passes the quadlet type
// it already knows instead, and an absent/unsuffixed type strips nothing
// rather than risking a too-short stem.
function stemFromUnitName(unitName, quadletType) {
    let result = unitName.endsWith('.service') ? unitName.slice(0, -'.service'.length) : unitName;
    if (quadletType) {
        const type = quadletType.toLowerCase();
        if (SUFFIXED_QUADLET_TYPES.has(type)) {
            const suffix = '-' + type;
            if (result.endsWith(suffix)) {
                result = result.slice(0, -suffix.length);
            }
        }
    }
    return result;
}

// Mark the clicked quadlet tree button as selected (inset state).
// Called inline from partials/quadlet_tree.html onclick.
function setSelectedQuadletBtn(el) {
    document.querySelectorAll('.quadlet-tree-btn.is-selected')
        .forEach(function (b) { b.classList.remove('is-selected'); });
    if (el) el.classList.add('is-selected');
}

// Re-apply the .is-selected class after htmx swaps the quadlet tree.
// Source of truth is state._selectedContainerStem / _selectedContainerServerId,
// set by selectContainerStem() — the editor pane is the real state, we're
// just re-syncing the sidebar visual to match.
function reapplyQuadletSelection() {
    const stem = state._selectedContainerStem;
    const sid  = state._selectedContainerServerId;
    if (!stem || !sid) return;
    const btn = document.querySelector(
        '.quadlet-tree-btn[data-stem="' + stem + '"][data-server-id="' + sid + '"]'
    );
    if (btn) btn.classList.add('is-selected');
}
// Restore the saved quadlet selection after the tree loads via HTMX.
// Uses a once-flag so subsequent tree re-renders don't clobber user clicks.
function restoreQuadletSelection() {
    if (state._quadletRestored) return;
    let saved;
    try {
        saved = JSON.parse(localStorage.getItem('qm-selected-quadlet'));
    } catch {
        // Ignore localStorage restrictions or parsing errors
    }
    if (!saved?.stem || !saved?.serverId) return;
    const btn = document.querySelector(
        '.quadlet-tree-btn[data-stem="' + saved.stem + '"][data-server-id="' + saved.serverId + '"]'
    );
    if (!btn) return;
    state._quadletRestored = true;
    btn.click();
}

document.body.addEventListener('htmx:afterSwap', function (e) {
    // Fire on any swap that could have replaced a tree button. Cheap — a
    // single querySelector with no match is negligible.
    if (e.target?.querySelector?.('.quadlet-tree-btn')) {
        reapplyQuadletSelection();
        restoreQuadletSelection();
    }
    // Restore collapse states when the server list is (re)loaded via HTMX.
    if (e.target?.querySelector?.('li[data-server-id]')) {
        restoreServerCollapseStates();
    }
    // Sync expand button tooltip after editor pane swaps
    syncInspectorToggleBtn();
    // Re-apply poll-health warning badges after the server tree reloads
    applyPollHealthBadges();
    // The Monitor's server dropdown is swapped whole on reload-servers, which
    // drops the user's selection along with the old options.
    if (e.target?.id === 'monitoring-server-select') {
        restoreMonitoringServerSelection(e.target);
    }
});

// ── Monaco Editor Configuration ──────────────────────────
require.config({ paths: { 'vs': '/static/vendor/monaco/vs' }});

// Ensure Monaco layout handles window sizing
window.addEventListener('resize', function() {
    if (window.editor) {
        window.editor.layout();
    }
});


// ── Notifications Configuration ──────────────────────────
if ('Notification' in window && Notification.permission !== 'granted' && Notification.permission !== 'denied') {
    Notification.requestPermission();
}


function checkQuadletStartup(watchId, stem, serverId, unitName, scope) {
    Reflect.deleteProperty(pendingStarts, watchId);
    
    const running = Reflect.get(runningContainersBySid, serverId) || new Set();
    let isRunning = false;
    running.forEach(function(name) {
        if (name.includes(stem) || stem.includes(name)) {
            isRunning = true;
        }
    });
    
    if (isRunning) {
        sendNotification('Success', 'Quadlet ' + stem + ' started successfully');
    } else {
        // Fetch status HTML to extract the error message
        const statusUrl = '/api/systemctl/status/' + serverId + '?unit=' + encodeURIComponent(unitName) + '&scope=' + encodeURIComponent(scope);
        fetch(statusUrl)
            .then(function(res) { return res.text(); })
            .then(function(html) {
                const doc = new window.DOMParser().parseFromString(html, 'text/html');
                const lines = doc.body.textContent.split('\n');
                let errorMsg = 'Unknown error';
                for (const line of lines) {
                    const trimmed = line.trim();
                    if (trimmed.includes('Failed') || trimmed.includes('failed with') || trimmed.includes('error')) {
                        errorMsg = trimmed;
                        break;
                    }
                }
                sendNotification('Error', 'Quadlet ' + stem + ' failed with error ' + errorMsg);
            })
            .catch(function() {
                sendNotification('Error', 'Quadlet ' + stem + ' failed to start');
            });
    }
}

document.body.addEventListener('htmx:beforeRequest', function(evt) {
    const path = evt.detail.pathInfo.requestPath;
    const params = evt.detail.requestConfig.parameters || {};
    let unitName = '';
    let serverId = null;
    let scope = '';
    let action = '';
    let quadletType = '';

    if (path.includes('/api/systemctl/')) {
        const urlParts = path.split('?');
        serverId = Number.parseInt(urlParts[0].split('/').pop(), 10);
        const searchParams = new URLSearchParams(urlParts[1] || window.location.search);
        unitName = params.unit || searchParams.get('unit') || '';
        scope = params.scope || searchParams.get('scope') || '';
        action = params.action || searchParams.get('action') || '';
        quadletType = params.quadlet_type || searchParams.get('quadlet_type') || '';
    } else if (path.includes('/api/save')) {
        unitName = params.unit_name || '';
        serverId = Number.parseInt(params.server_id, 10);
        scope = params.scope || '';
        action = 'restart'; // saving implies a restart
        quadletType = params.quadlet_type || '';
    }

    if (unitName && serverId) {
        const stem = stemFromUnitName(unitName, quadletType).toLowerCase();
        const watchId = serverId + ':' + stem;
        
        if (action === 'stop') {
            manualStops.add(watchId);
        } else if (action === 'start' || action === 'restart') {
            manualStops.delete(watchId);
            const pending = Reflect.get(pendingStarts, watchId);
            if (pending) clearTimeout(pending.timer);
            Reflect.set(pendingStarts, watchId, {
                unit: unitName,
                serverId: serverId,
                scope: scope,
                timer: setTimeout(function() {
                    checkQuadletStartup(watchId, stem, serverId, unitName, scope);
                }, 5000)
            });
        }
    }
});

document.body.addEventListener('htmx:responseError', function(evt) {
    const xhr = evt.detail.xhr;
    const toast = document.getElementById('status-toast');
    if (!toast) return;

    let message = '';
    const responseText = xhr.responseText || '';
    try {
        const parsed = JSON.parse(responseText);
        if (parsed?.detail !== undefined) {
            message = parsed.detail;
        } else {
            message = responseText;
        }
    } catch {
        // Not JSON -- fall back to the raw body as the toast message.
        message = responseText;
    }
    if (!message) {
        message = 'Request failed (HTTP ' + xhr.status + ')';
    }

    toast.textContent = '';
    toast.appendChild(
        el('div', { className: 'toast-msg toast-danger toast-enter' }, message)
    );
    // Auto-dismiss after 8 seconds
    setTimeout(function() {
        if (toast.querySelector('.toast-enter')) {
            toast.textContent = '';
        }
    }, 8000);
});

document.body.addEventListener('user-updated', function(evt) {
    const toast = document.getElementById('status-toast');
    if (!toast) return;

    const message = evt.detail?.message || 'User updated';

    toast.textContent = '';
    toast.appendChild(
        el('div', { className: 'toast-msg toast-success toast-enter' }, message)
    );
    // Auto-dismiss after 8 seconds
    setTimeout(function() {
        if (toast.querySelector('.toast-enter')) {
            toast.textContent = '';
        }
    }, 8000);
});


// ── Stats Chart ──────────────────────────────────────────
const HISTORY_COLORS = [
    'rgba(20, 184, 166, 1)',   // teal  — matches brand-primary
    'rgba(16, 185, 129, 1)',   // emerald
    'rgba(244, 63, 94, 1)',    // rose
    'rgba(245, 158, 11, 1)',   // amber
    'rgba(6, 182, 212, 1)',    // cyan
    'rgba(239, 68, 68, 1)',    // red
    'rgba(168, 85, 247, 1)',   // violet
    'rgba(251, 146, 60, 1)',   // orange
];

// Colors are keyed off container name, not position: the table swatch and
// the chart line have to agree, but the two dataset-building paths visit
// containers in different orders.

// An empty set means every series is visible; a non-empty set is the exact
// set of visible container names. Both history charts share this selection.

// Single source of truth for "is this series/swatch on": both the row
// renderer and the click refresh use it, so the button state and
// `ds.hidden` can never drift apart.
function chartSwatchIsOn(name) {
    return monitorChartSelection.size === 0 || monitorChartSelection.has(name);
}

// Sets a swatch button's aria-pressed and class from the shared predicate.
// `chart-swatch` is the permanent identity class (styling and test hooks key
// off it regardless of state); `chart-swatch-off` is added alongside it,
// never in place of it, when the series is hidden.
function applySwatchState(btn, name) {
    const on = chartSwatchIsOn(name);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.className = on ? 'chart-swatch' : 'chart-swatch chart-swatch-off';
}

function chartColorFor(name) {
    if (chartColorByName.has(name)) {
        return chartColorByName.get(name);
    }
    const color = HISTORY_COLORS[chartColorByName.size % HISTORY_COLORS.length];
    chartColorByName.set(name, color);
    return color;
}

function applyChartSelection(chart) {
    if (!chart) return;
    chart.data.datasets.forEach(function(ds) {
        ds.hidden = monitorChartSelection.size > 0 && !monitorChartSelection.has(ds.label);
    });
}

// One click on a container's swatch. From all-visible, it isolates that
// container; from a subset it adds or removes; and clicking the only selected
// container clears the selection, so a user is never stranded in a filtered view.
function toggleChartSelection(name) {
    if (!monitorChartSelection.has(name)) {
        monitorChartSelection.add(name);
    } else if (monitorChartSelection.size >= 2) {
        monitorChartSelection.delete(name);
    } else {
        monitorChartSelection.clear();
    }
    applyChartSelection(state.cpuHistoryChart);
    applyChartSelection(state.memHistoryChart);
    if (state.cpuHistoryChart) state.cpuHistoryChart.update('none');
    if (state.memHistoryChart) state.memHistoryChart.update('none');
    refreshChartSwatches();
}

// Gives the click immediate feedback without waiting for the next stats
// frame to re-render the table.
function refreshChartSwatches() {
    document.querySelectorAll('#monitoring-stats-table button.chart-swatch').forEach(function(btn) {
        applySwatchState(btn, btn.dataset.container);
    });
}


function getChartTheme() {
    const s = getComputedStyle(document.documentElement);
    const get = function(v) { return s.getPropertyValue(v).trim(); };
    const brand = get('--brand-primary');
    const border = get('--border-color');
    return {
        accent:       brand,
        accentBg:     hexToRgba(brand, 0.6),
        secondary:    '#f43f5e',
        secondaryBg:  'rgba(244, 63, 94, 0.6)',
        tickColor:    get('--text-muted'),
        gridColor:    hexToRgba(border, 0.4),
        legendColor:  get('--text-primary'),
        tooltipBg:    get('--bg-base'),
        tooltipTitle: get('--text-primary'),
        tooltipBody:  get('--text-muted'),
        tooltipBorder: hexToRgba(border, 0.6),
    };
}

function patchChartOptions(opts, t) {
    opts.scales.y.ticks.color          = t.tickColor;
    opts.scales.y.grid.color           = t.gridColor;
    opts.scales.x.ticks.color          = t.tickColor;
    opts.plugins.legend.labels.color   = t.legendColor;
    opts.plugins.tooltip.backgroundColor = t.tooltipBg;
    opts.plugins.tooltip.titleColor    = t.tooltipTitle;
    opts.plugins.tooltip.bodyColor     = t.tooltipBody;
    opts.plugins.tooltip.borderColor   = t.tooltipBorder;
}

function applyChartTheme() {
    const t = getChartTheme();
    const charts = [];
    if (typeof monitoringChart !== 'undefined' && monitoringChart) {
        charts.push(monitoringChart);
    }
    charts.forEach(function(chart) {
        if (!chart) return;
        chart.data.datasets[0].backgroundColor = t.accentBg;
        chart.data.datasets[0].borderColor      = t.accent;
        chart.data.datasets[1].backgroundColor  = t.secondaryBg;
        chart.data.datasets[1].borderColor      = t.secondary;
        patchChartOptions(chart.options, t);
        chart.update('none');
    });
    if (typeof healthHistoryChart !== 'undefined' && healthHistoryChart) {
        patchChartOptions(healthHistoryChart.options, t);
        healthHistoryChart.update('none');
    }
    // Monitor time-series charts build their own per-container datasets, so only
    // the shared axis/legend/tooltip colors need repainting on a theme switch.
    [state.cpuHistoryChart, state.memHistoryChart].forEach(function(chart) {
        if (!chart) return;
        patchChartOptions(chart.options, t);
        chart.update('none');
    });
}

function applyEditorTheme() {
    if (!window.monaco || !window.editor) return;
    let pref = 'follow';
    try {
        pref = localStorage.getItem('qm-editor-theme') || 'follow';
    } catch {
        pref = 'follow';
    }
    if (pref === 'light') {
        window.monaco.editor.setTheme('vs');
    } else if (pref === 'dark') {
        window.monaco.editor.setTheme('vs-dark');
    } else {
        const resolved = document.documentElement.dataset.theme;
        window.monaco.editor.setTheme(resolved === 'light' ? 'vs' : 'vs-dark');
    }
}

// Track which server the user is currently working in.
// The stats chart only renders updates for this server.
// null = show whichever server reports first (auto-set on first update).

// Last unhealthy count announced to #monitor-health-status, so repeated
// SSE ticks with an unchanged count do not re-trigger the live region.
let lastAnnouncedUnhealthy = null;

// Currently selected container stem in the inspector (lowercase).
// Set to true after the saved quadlet selection has been restored once,
// so subsequent htmx:afterSwap tree re-renders don't override user clicks.

function selectContainerStem(stem, serverId, scope, type) {
    state._selectedContainerStem = (stem || '').toLowerCase();
    state._selectedContainerServerId = Number.parseInt(serverId, 10);
    state._selectedContainerScope = scope || 'global';
    state._selectedContainerType = (type || '').toLowerCase();
    try {
        localStorage.setItem('qm-selected-quadlet', JSON.stringify({
            stem: state._selectedContainerStem,
            serverId: state._selectedContainerServerId,
            scope: state._selectedContainerScope
        }));
    } catch {
        // Ignore localStorage restrictions
    }
    const emptyEl = document.getElementById('inspector-empty-state');
    if (emptyEl) emptyEl.style.display = stem ? 'none' : '';
    updateInspectorStatsCard();
    updateInspectorActivityLog();
}

function updateInspectorStatsCard() {
    const card = document.getElementById('container-stats-card');
    if (!card) return;

    const stem = state._selectedContainerStem;
    const serverId = state._selectedContainerServerId;
    if (!stem || !serverId) {
        card.classList.add('hidden');
        hideTerminalSection();
        return;
    }

    const serverStats = Reflect.get(lastStatsPerServer, serverId);
    const running = Reflect.get(runningContainersBySid, serverId) || new Set();

    // Find matching container in stats data
    let matched = null;
    if (serverStats) {
        (serverStats.containers || []).forEach(function(c) {
            const cName = (c.name || '').toLowerCase();
            if (cName.includes(stem) || stem.includes(cName)) {
                matched = c;
            }
        });
    }

    // Check if container is running (even if stats haven't arrived yet)
    let isRunning = false;
    running.forEach(function(name) {
        if (name.includes(stem) || stem.includes(name)) {
            isRunning = true;
        }
    });

    card.classList.remove('hidden');

    // Enable/disable terminal connect button based on running state
    const connectBtn = document.getElementById('terminal-connect-btn');
    if (connectBtn) connectBtn.disabled = !isRunning;
    // Tabs are user-managed; do not auto-close an existing session when the container stops.

    // Clear card safely
    card.textContent = '';

    if (matched) {
        const gridItems = [
            { label: 'CPU', value: matched.cpu },
            { label: 'Memory', value: matched.mem },
            { label: 'Net I/O', value: matched.net_io },
            { label: 'PIDs', value: matched.pids }
        ].map(function(stat) {
            return el('div', { className: 'stats-card-item' }, [
                el('span', { className: 'stats-card-label' }, stat.label),
                el('span', { className: 'stats-card-value' }, stat.value)
            ]);
        });

        card.appendChild(el('div', { className: 'stats-card-title' }, [
            el('span', { className: 'status-dot dot-running', style: { width: '8px', height: '8px' } }),
            matched.name
        ]));
        card.appendChild(el('div', { className: 'stats-card-grid' }, gridItems));
    } else if (!isRunning) {
        card.appendChild(el('div', { className: 'stats-card-title' }, stem));
        card.appendChild(el('div', { className: 'stats-card-not-running' }, 'Container not running'));
    } else {
        card.appendChild(el('div', { className: 'stats-card-title' }, [
            el('span', { className: 'status-dot dot-running', style: { width: '8px', height: '8px' } }),
            stem
        ]));
        card.appendChild(el('div', { className: 'stats-card-not-running' }, 'Waiting for stats...'));
    }
}

function updateInspectorActivityLog() {
    const activityLog = document.getElementById('container-activity-log');
    if (!activityLog) return;

    const stem = state._selectedContainerStem;
    const serverId = state._selectedContainerServerId;
    if (!stem || !serverId) {
        activityLog.classList.add('hidden');
        return;
    }

    activityLog.classList.remove('hidden');

    // Fetch activity events from the API
    fetch('/api/activity/' + serverId + '?container=' + encodeURIComponent(stem) + '&limit=10')
        .then(function(response) {
            if (!response.ok) throw new Error('Failed to fetch activity');
            return response.json();
        })
        .then(function(data) {
            const listEl = activityLog.querySelector('.activity-list');
            listEl.innerHTML = '';
            if (!data.events || data.events.length === 0) {
                const emptyDiv = document.createElement('div');
                emptyDiv.className = 'text-muted italic p-2';
                emptyDiv.textContent = 'No events recorded';
                listEl.appendChild(emptyDiv);
                return;
            }

            data.events.forEach(function(event) {
                let icon = '';
                switch (event.event_type) {
                    case 'start': icon = '▶'; break;
                    case 'stop': icon = '⏹'; break;
                    case 'restart': icon = '🔄'; break;
                    case 'failure': icon = '⚠'; break;
                    default: icon = '•';
                }

                const relTime = getRelativeTime(event.occurred_at);
                const triggeredBy = event.triggered_by ? ' by ' + event.triggered_by : '';

                const itemDiv = document.createElement('div');
                itemDiv.className = 'activity-item';

                const iconSpan = document.createElement('span');
                iconSpan.className = 'activity-icon';
                iconSpan.textContent = icon;
                itemDiv.appendChild(iconSpan);

                const typeSpan = document.createElement('span');
                typeSpan.className = 'activity-type';
                typeSpan.textContent = event.event_type;
                itemDiv.appendChild(typeSpan);

                const timeSpan = document.createElement('span');
                timeSpan.className = 'activity-time';
                timeSpan.textContent = relTime;
                itemDiv.appendChild(timeSpan);

                const userSpan = document.createElement('span');
                userSpan.className = 'activity-user';
                userSpan.textContent = triggeredBy;
                itemDiv.appendChild(userSpan);

                listEl.appendChild(itemDiv);
            });
        })
        .catch(function(err) {
            console.error('Error fetching activity:', err);
            const listEl = activityLog.querySelector('.activity-list');
            listEl.innerHTML = '';
            const errorDiv = document.createElement('div');
            errorDiv.className = 'text-muted italic p-2';
            errorDiv.textContent = 'Failed to load activity';
            listEl.appendChild(errorDiv);
        });
}



// Called from quadlet_tree.html when the user clicks a file button.
function setActiveServer(serverId) {
    serverId = Number.parseInt(serverId, 10);
    if (state.activeServerId === serverId) return;
    state.activeServerId = serverId;
    // Re-render immediately with cached data for this server, if we have it.
    const cached = Reflect.get(lastStatsPerServer, serverId);
    if (cached) {
        applyStatusDots(serverId);
    }
}

/**
 * Update all status dots for a given server based on the cached
 * runningContainersBySid map.
 *
 * Quadlet filenames like "my-app.container" map to container name stems by
 * stripping the extension. Podman container names are compared
 * case-insensitively — podman often uses the stem directly as the container
 * name, though operators may prefix/suffix it. We do a "contains" check so
 * that "my-app" matches a running container named "systemd-my-app".
 *
 * @param {number} serverId
 */
function applyStatusDots(serverId) {
    const running = Reflect.get(runningContainersBySid, serverId) || new Set();
    const serverStats = Reflect.get(lastStatsPerServer, serverId);
    const containersByName = {};
    if (serverStats) {
        (serverStats.containers || []).forEach(function(c) {
            Reflect.set(containersByName, (c.name || '').toLowerCase(), c);
        });
    }

    const dots = document.querySelectorAll('.status-dot[data-server-id="' + serverId + '"]');
    dots.forEach(function(dot) {
        const stem = (dot.dataset.unitStem || '').toLowerCase();
        let isRunning = false;
        let matchedContainer = null;
        running.forEach(function(name) {
            if (name.includes(stem) || stem.includes(name)) {
                isRunning = true;
                const matched = Reflect.get(containersByName, name);
                if (matched) matchedContainer = matched;
            }
        });
        dot.classList.remove('dot-running', 'dot-stopped', 'dot-failed');
        if (isRunning) {
            dot.classList.add('dot-running');
            dot.title = matchedContainer
                ? 'Running — CPU: ' + matchedContainer.cpu + ' | MEM: ' + matchedContainer.mem
                : 'Running';
        } else {
            dot.classList.add('dot-stopped');
            dot.title = 'Stopped / not running';
        }
    });
}


function _buildTimeSeriesConfig() {
  const t = getChartTheme();
  return {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        y: {
          beginAtZero: true,
          suggestedMax: 5,
          ticks: {
            color: t.tickColor,
            font: { size: 10 },
            callback: function(v) { return v + '%'; }
          },
          grid: { color: t.gridColor }
        },
        x: {
          ticks: {
            color: t.tickColor,
            font: { size: 10 },
            maxTicksLimit: 8,
            maxRotation: 0
          },
          grid: { display: false }
        }
      },
      plugins: {
        // The container table is the legend now (issue #256); the canvas
        // legend would just duplicate the chart-swatch buttons.
        legend: { display: false },
        tooltip: {
          backgroundColor: t.tooltipBg,
          titleColor: t.tooltipTitle,
          bodyColor: t.tooltipBody,
          borderColor: t.tooltipBorder,
          borderWidth: 1,
          cornerRadius: 6,
          padding: 8,
          callbacks: {
            label: function(ctx) { return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%'; }
          }
        }
      }
    }
  };
}

function initCpuChart() {
  const ctx = document.getElementById('cpu-history-chart');
  if (!ctx) return;
  state.cpuHistoryChart = new Chart(ctx, _buildTimeSeriesConfig());
}

function initMemChart() {
  const ctx = document.getElementById('mem-history-chart');
  if (!ctx) return;
  state.memHistoryChart = new Chart(ctx, _buildTimeSeriesConfig());
}


function loadMonitorCharts(minutes, btnEl) {
  state._monitorChartMinutes = minutes;

  if (btnEl) {
    document.querySelectorAll('.health-range-btn').forEach(function(b) { b.classList.remove('active'); });
    btnEl.classList.add('active');
  }

  const serverId = state._monitoringServerId;
  if (!serverId) return;

  fetch('/api/health/history/' + serverId + '?minutes=' + minutes)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      const emptyEl = document.getElementById('monitor-charts-empty');
      const errorEl = document.getElementById('monitor-charts-error');
      if (errorEl) errorEl.style.display = 'none';

      if (!data || data.length === 0) {
        if (emptyEl) emptyEl.style.display = '';
        return;
      }
      if (emptyEl) emptyEl.style.display = 'none';

      if (!state.cpuHistoryChart || !state.memHistoryChart) return;

      // Build unified sorted timestamp labels from all containers
      const tsSet = new Set();
      data.forEach(function(c) { c.history.forEach(function(p) { tsSet.add(p.ts); }); });
      const tsSorted = Array.from(tsSet).sort(function(a, b) { return a - b; });

      const _rangeMinutes = state._monitorChartMinutes;
      const _dayNames = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
      const labels = tsSorted.map(function(ts) {
        const d = new Date(ts * 1000);
        const hh = d.getHours().toString().padStart(2, '0');
        const mm = d.getMinutes().toString().padStart(2, '0');
        const ss = d.getSeconds().toString().padStart(2, '0');
        if (_rangeMinutes <= 60) {
          return hh + ':' + mm + ':' + ss;
        } else if (_rangeMinutes <= 1440) {
          return hh + ':' + mm;
        } else {
          return _dayNames[d.getDay()] + ' ' + hh + ':' + mm;
        }
      });

      // Apply container filter to chart data
      const filteredData = state.monitorContainerFilter
        ? data.filter(function(c) { return (c.container_name || '').toLowerCase().includes(state.monitorContainerFilter); })
        : data;

      const cpuDatasets = filteredData.map(function(c) {
        const byTs = {};
        c.history.forEach(function(p) { Reflect.set(byTs, p.ts, p.cpu !== null ? p.cpu : null); });
        const color = chartColorFor(c.container_name);
        return {
          label: c.container_name,
          data: tsSorted.map(function(ts) {
            const val = Reflect.get(byTs, ts);
            return val !== undefined ? val : null;
          }),
          borderColor: color,
          backgroundColor: color.replace('1)', '0.08)'),
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          spanGaps: false,
        };
      });

      const memDatasets = filteredData.map(function(c) {
        const byTs = {};
        c.history.forEach(function(p) { Reflect.set(byTs, p.ts, p.mem !== null ? p.mem : null); });
        const color = chartColorFor(c.container_name);
        return {
          label: c.container_name,
          data: tsSorted.map(function(ts) {
            const val = Reflect.get(byTs, ts);
            return val !== undefined ? val : null;
          }),
          borderColor: color,
          backgroundColor: color.replace('1)', '0.08)'),
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          spanGaps: false,
        };
      });

      state.cpuHistoryChart.data.labels = labels;
      state.cpuHistoryChart.data.datasets = cpuDatasets;
      applyChartSelection(state.cpuHistoryChart);
      state.cpuHistoryChart.update();

      state.memHistoryChart.data.labels = labels;
      state.memHistoryChart.data.datasets = memDatasets;
      applyChartSelection(state.memHistoryChart);
      state.memHistoryChart.update();
    })
    .catch(function(err) {
      console.error('Monitor chart fetch error:', err);
      const errorEl = document.getElementById('monitor-charts-error');
      if (errorEl) errorEl.style.display = '';
    });
}

function parsePercent(val) {
    if (typeof val === 'string') {
        return Number.parseFloat(val.replaceAll('%', '')) || 0;
    }
    return Number.parseFloat(val) || 0;
}

function getPercentClass(val) {
    if (val >= 80) return 'cell-danger';
    if (val >= 60) return 'cell-warn';
    return '';
}

function getHealthBadgeInfo(health) {
    const h = health || '';
    if (h === '') return { badgeClass: 'running', label: 'running' };
    if (h === 'healthy') return { badgeClass: 'healthy', label: h };
    if (h === 'starting') return { badgeClass: 'starting', label: h };
    return { badgeClass: 'unhealthy', label: h };
}

// The Monitor table joins each container to its systemd unit by the unit name
// the stats engine attaches to the container. A server that has not reported
// units yet indexes to null, which renders as a placeholder rather than as a
// container with no unit.
function buildUnitIndex(units) {
    if (units === undefined || units === null) return null;
    const index = new Map();
    units.forEach(function(u) {
        if (u?.unit) index.set(u.unit, u);
    });
    return index;
}

function getUnitBadgeInfo(activeState = '') {
    if (activeState === 'failed') return { badgeClass: 'unit-failed', label: activeState };
    if (activeState === 'active') return { badgeClass: 'unit-active', label: activeState };
    return { badgeClass: 'unit-other', label: activeState || STAT_PLACEHOLDER };
}

// A stopped systemd unit has no running container, so the stats engine never
// reports it among containers. The Monitor table still needs a row for it, so
// we synthesize placeholder rows for any unit that no container has claimed.
function mergeUnitRows(containers, units) {
    if (units === undefined || units === null) return containers;
    const claimed = new Set();
    containers.forEach(function(c) {
        if (c.unit) claimed.add(c.unit);
        // A container whose PODMAN_SYSTEMD_UNIT label is missing still belongs
        // to its unit. Quadlet names the container "systemd-<base>" unless
        // ContainerName= overrides it, so the name stem claims the unit too,
        // or the container would be drawn twice: once real, once synthesized.
        const stem = (c.name || '').replace(/^systemd-/, '');
        if (stem) claimed.add(stem + '.service');
    });
    const synthesized = [];
    units.forEach(function(u) {
        if (u.unit && !claimed.has(u.unit)) {
            synthesized.push({
                name: u.unit.replace(/\.service$/, ''),
                unit: u.unit,
                health: '',
                not_running: true,
                cpu: STAT_PLACEHOLDER,
                mem: STAT_PLACEHOLDER,
                mem_usage: STAT_PLACEHOLDER,
                net_io: STAT_PLACEHOLDER,
                pids: STAT_PLACEHOLDER
            });
        }
    });
    return containers.concat(synthesized);
}

function applyPercentSeverity(td, severityClass) {
    if (!severityClass) return;
    const glyph = severityClass === 'cell-danger' ? '▲' : '●';
    const word = severityClass === 'cell-danger' ? 'high' : 'elevated';

    const flag = document.createElement('span');
    flag.className = 'cell-flag';
    flag.setAttribute('aria-hidden', 'true');
    flag.textContent = glyph;
    td.appendChild(flag);

    const hidden = document.createElement('span');
    hidden.className = 'visually-hidden';
    hidden.textContent = word;
    td.appendChild(hidden);
}

// A synthesized row stands for a unit with no running container, so it has no
// health to report; its status comes from the systemd state instead.
function getStatusBadgeInfo(c, unitRec) {
    if (c.not_running) return getUnitBadgeInfo(unitRec?.active_state);
    return getHealthBadgeInfo(c.health);
}

function renderContainerRow(c, unitIndex) {
    const cpuClass = getPercentClass(parsePercent(c.cpu));
    const memClass = getPercentClass(parsePercent(c.mem));
    const unitRec = unitIndex && c.unit ? unitIndex.get(c.unit) : null;
    const badgeInfo = getStatusBadgeInfo(c, unitRec);

    const tr = document.createElement('tr');
    tr.className = 'border-b';

    const tdSwatch = document.createElement('td');
    tdSwatch.className = 'p-4 chart-swatch-cell';
    if (!c.not_running) {
        const swatchBtn = document.createElement('button');
        swatchBtn.type = 'button';
        swatchBtn.dataset.container = c.name;
        swatchBtn.style.backgroundColor = chartColorFor(c.name);
        swatchBtn.setAttribute('aria-label', 'Toggle ' + c.name + ' in the history charts');
        applySwatchState(swatchBtn, c.name);
        swatchBtn.addEventListener('click', function() {
            toggleChartSelection(c.name);
        });
        tdSwatch.appendChild(swatchBtn);
    }
    tr.appendChild(tdSwatch);

    const tdName = document.createElement('td');
    tdName.className = 'text-left p-4 text-accent font-semibold';
    tdName.textContent = c.name;
    tr.appendChild(tdName);

    const tdStatus = document.createElement('td');
    tdStatus.className = 'p-4 text-left';
    const badgeSpan = document.createElement('span');
    badgeSpan.className = 'stat-badge ' + badgeInfo.badgeClass;
    badgeSpan.textContent = badgeInfo.label;
    tdStatus.appendChild(badgeSpan);
    tr.appendChild(tdStatus);

    const tdUnit = document.createElement('td');
    tdUnit.className = 'p-4 text-left';
    if (unitRec) {
        const unitInfo = getUnitBadgeInfo(unitRec.active_state);
        const unitBadge = document.createElement('span');
        unitBadge.className = 'stat-badge ' + unitInfo.badgeClass;
        unitBadge.textContent = unitInfo.label;
        tdUnit.appendChild(unitBadge);
        if (unitRec.n_restarts > 0) {
            // The restart count reads as a bare number to a screen reader, so
            // name it with a visually-hidden label.
            const count = document.createElement('span');
            count.className = 'cell-flag';
            count.setAttribute('aria-hidden', 'true');
            count.textContent = '\u00d7' + unitRec.n_restarts;
            tdUnit.appendChild(count);

            const hidden = document.createElement('span');
            hidden.className = 'visually-hidden';
            hidden.textContent = unitRec.n_restarts + ' restarts';
            tdUnit.appendChild(hidden);
        }
    } else {
        tdUnit.textContent = STAT_PLACEHOLDER;
    }
    tr.appendChild(tdUnit);

    const tdCpu = document.createElement('td');
    tdCpu.className = 'p-4 text-right' + (cpuClass ? ' ' + cpuClass : '');
    tdCpu.textContent = c.cpu;
    applyPercentSeverity(tdCpu, cpuClass);
    tr.appendChild(tdCpu);

    const tdMem = document.createElement('td');
    tdMem.className = 'p-4 text-right' + (memClass ? ' ' + memClass : '');
    tdMem.textContent = c.mem;
    applyPercentSeverity(tdMem, memClass);
    tr.appendChild(tdMem);

    const tdNet = document.createElement('td');
    tdNet.className = 'p-4 text-right net-io-cell';
    tdNet.textContent = c.net_io;
    tr.appendChild(tdNet);

    return tr;
}

function renderContainerStatsTable(tableElId, data) {
    const tableEl = document.getElementById(tableElId);
    if (!tableEl) return;

    tableEl.innerHTML = '';
    const containers = data.containers || [];

    if (containers.length === 0) {
        const emptyDiv = document.createElement('div');
        emptyDiv.className = 'p-4 text-muted italic';
        emptyDiv.textContent = 'No containers running on ' + (data.server_name || 'server');
        tableEl.appendChild(emptyDiv);
        return;
    }

    const table = document.createElement('table');
    table.className = 'w-full';

    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    headerRow.className = 'text-muted';

    const headers = [
        { text: 'Series color', align: 'left', visuallyHidden: true },
        { text: 'Container', align: 'left' },
        { text: 'Status', align: 'left' },
        { text: 'Unit', align: 'left' },
        { text: 'CPU', align: 'right' },
        { text: 'MEM', align: 'right' },
        { text: 'NET I/O', align: 'right' }
    ];

    headers.forEach(function(h) {
        const th = document.createElement('th');
        th.className = (h.align === 'left' ? 'text-left p-4' : 'p-4 text-right');
        th.scope = 'col';
        if (h.visuallyHidden) {
            const label = document.createElement('span');
            label.className = 'visually-hidden';
            label.textContent = h.text;
            th.appendChild(label);
        } else {
            th.textContent = h.text;
        }
        headerRow.appendChild(th);
    });

    // <caption> must be the table's first child per the HTML spec, so it is
    // appended before <thead>.
    const caption = document.createElement('caption');
    caption.className = 'visually-hidden';
    caption.textContent = 'Container resource usage for ' + (data.server_name || 'server');
    table.appendChild(caption);

    thead.appendChild(headerRow);
    table.appendChild(thead);

    const unitIndex = buildUnitIndex(data.units);

    const tbody = document.createElement('tbody');
    containers.forEach(function(c) {
        const tr = renderContainerRow(c, unitIndex);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableEl.appendChild(table);

    const footerDiv = document.createElement('div');
    footerDiv.className = 'p-4 text-muted text-right text-xs';
    footerDiv.textContent = data.server_name || '';
    tableEl.appendChild(footerDiv);
}

function isManualStop(serverId, oldName) {
  let wasManual = false;
  manualStops.forEach(function(manualKey) {
    const parts = manualKey.split(':');
    const mServerId = Number.parseInt(parts[0], 10);
    const mStem = parts[1];
    if (mServerId === serverId && (oldName.includes(mStem) || mStem.includes(oldName))) {
      wasManual = true;
    }
  });
  return wasManual;
}

function detectUnexpectedlyStopped(serverId, oldSet, runningSet) {
  oldSet.forEach(function(oldName) {
    if (!runningSet.has(oldName)) {
      if (!isManualStop(serverId, oldName)) {
        sendNotification('Alert', 'Quadlet container ' + oldName + ' stopped or failed unexpectedly');
      }
    }
  });
}

function cacheServerStats(data) {
  Reflect.set(lastStatsPerServer, data.server_id, data);

  const oldSet = Reflect.get(runningContainersBySid, data.server_id) || new Set();

  const runningSet = new Set();
  (data.containers || []).forEach(function(c) {
    runningSet.add((c.name || '').toLowerCase());
  });
  Reflect.set(runningContainersBySid, data.server_id, runningSet);

  return { oldSet: oldSet, runningSet: runningSet };
}

// Gated on _monitoringServerId so errors only surface for the server the
// Monitor pane is currently displaying.
function handleStatsError(e) {
  try {
    const data = JSON.parse(e.data);

    if (data.server_id === state._monitoringServerId) {
      const monitoringTableEl = document.getElementById('monitoring-stats-table');
      if (monitoringTableEl) {
        monitoringTableEl.textContent = '';
        monitoringTableEl.appendChild(createStatsErrorDOM(data.server_name, data.error));
      }
    }
  } catch (err) {
    console.error('Stats error parse error:', err);
  }
}

function handleStatsUpdate(e) {
  try {
    const data = JSON.parse(e.data);
    _statsReceived = true;
    if (_statsWaitTimeout) { clearTimeout(_statsWaitTimeout); _statsWaitTimeout = null; }

    const sets = cacheServerStats(data);

    detectUnexpectedlyStopped(data.server_id, sets.oldSet, sets.runningSet);

    applyStatusDots(data.server_id);

    if (data.server_id === state._selectedContainerServerId) {
      updateInspectorStatsCard();
    }

    if (state.activeServerId === null) {
      state.activeServerId = data.server_id;
    }

    updateMonitoringView(data);
  } catch (err) {
    console.error('Stats parse error:', err);
  }
}

// ── Poll Health Badges ───────────────────────────────────
const _pollHealthState = {};

function updatePollHealth(data) {
  if (data?.scope !== 'server') return;
  _pollHealthState[data.server_id] = data;
  const badge = document.querySelector(".server-poll-warning[data-server-id=\"" + data.server_id + "\"]");
  if (!badge) return;
  if (data.healthy) {
    badge.setAttribute('hidden', '');
    badge.title = '';
    return;
  }
  badge.removeAttribute('hidden');
  if (data.reason === 'slow_fetch') {
    badge.title = 'Polling slow' + ' (' + Number(data.last_duration).toFixed(1) + 's)';
  } else {
    badge.title = 'Polling failing' + ' (' + data.consecutive_failures + ' consecutive failures)';
  }
}

function applyPollHealthBadges() {
  Object.keys(_pollHealthState).forEach(function(serverId) {
    updatePollHealth(_pollHealthState[serverId]);
  });
}

function updateCycleIndicator(cycle) {
  if (!cycle) return;
  const indicator = document.getElementById('sync-cycle-indicator');
  if (!indicator) return;
  indicator.textContent = '';
  indicator.title = 'Each sync cycle refreshes container status from every '
    + 'server. It has ' + cycle.interval + 's to finish; longer means data '
    + 'can lag.';
  if (cycle.budget_exceeded) {
    const flag = document.createElement('span');
    flag.className = 'cycle-flag';
    flag.setAttribute('aria-hidden', 'true');
    flag.textContent = '▲';
    indicator.appendChild(flag);

    const hidden = document.createElement('span');
    hidden.className = 'visually-hidden';
    hidden.textContent = 'warning';
    indicator.appendChild(hidden);

    indicator.appendChild(
      document.createTextNode(
        'Sync running slow (' + Number(cycle.duration).toFixed(1) + 's of '
          + cycle.interval + 's)'
      )
    );
  } else {
    indicator.appendChild(document.createTextNode('Sync on time'));
  }
  indicator.removeAttribute('hidden');
  indicator.classList.toggle('cycle-over-budget', cycle.budget_exceeded);
}

function fetchPollHealthSnapshot() {
  fetch('/api/poll-health')
    .then(function(resp) { return resp.json(); })
    .then(function(snapshot) {
      Object.keys(snapshot.servers || {}).forEach(function(serverId) {
        const entry = snapshot.servers[serverId];
        let reason;
        if (entry.healthy) {
          reason = 'recovered';
        } else if (entry.consecutive_failures > 0) {
          reason = 'consecutive_failures';
        } else {
          reason = 'slow_fetch';
        }
        _pollHealthState[serverId] = {
          scope: 'server',
          server_id: serverId,
          healthy: entry.healthy,
          reason: reason,
          consecutive_failures: entry.consecutive_failures,
          last_duration: entry.last_duration
        };
      });
      applyPollHealthBadges();
      updateCycleIndicator(snapshot.cycle);
    })
    .catch(function(err) {
      console.error('Poll health snapshot parse error:', err);
    });
}

function handleQuadletsChanged(data) {
  const container = document.querySelector(
    '.server-quadlet-tree[data-server-id="' + data.server_id + '"]'
  );
  if (!container) return;
  htmx.ajax('GET', '/api/quadlets/' + data.server_id,
            { target: container, swap: 'innerHTML' });
}

function createStatsErrorDOM(serverName, errorMsg) {
  return el('div', { className: 'p-4 text-danger' }, [
    el('div', { className: 'font-bold mb-1' }, '⚠ Stats unavailable for ' + (serverName || 'server')),
    el('div', { className: 'text-xs text-muted' }, errorMsg || 'Unknown error'),
    el('div', { className: 'text-xs text-muted mt-1' }, 'Will retry automatically…')
  ]);
}

// ── SSE Connection ───────────────────────────────────────
function connectSSE() {
  const evtSource = new EventSource('/api/events');

  // Stats updates (every 5s from stats_engine)
  evtSource.addEventListener('stats_update', handleStatsUpdate);

  // Poll health events (from sync poller, per-server scope only)
  evtSource.addEventListener('poll_health', function(e) {
    try {
      const data = JSON.parse(e.data);
      if (data.scope === 'cycle') {
        updateCycleIndicator(data);
      } else {
        updatePollHealth(data);
      }
    } catch (err) {
      console.error('Poll health parse error:', err);
    }
  });

  // Stats error events (when podman is unreachable/timed out)
  evtSource.addEventListener('stats_error', handleStatsError);

    // File change notifications (from sync_engine)
    evtSource.addEventListener('file_changed', function(e) {
        try {
            const data = JSON.parse(e.data);
            const toast = document.getElementById('status-toast');
            if (toast) {
                toast.textContent = '';
                toast.appendChild(
                    el('div', { className: 'toast-msg toast-warning toast-enter' }, '⚠ ' + data.message + ' (' + data.file_path + ')')
                );
                // Auto-dismiss after 8 seconds
                setTimeout(function() {
                    if (toast.querySelector('.toast-enter')) {
                        toast.textContent = '';
                    }
                }, 8000);
            }
        } catch (err) {
            console.error('File changed parse error:', err);
        }
    });

    evtSource.addEventListener('quadlets_changed', function (e) {
      try {
        window.handleQuadletsChanged(JSON.parse(e.data));
      } catch (err) {
        console.error('Quadlets changed parse error:', err);
      }
    });

    evtSource.onerror = function() {
        console.warn('SSE connection lost, reconnecting in 3s...');
        evtSource.close();
        setTimeout(connectSSE, 3000);
    };
}


// ── Initialize on DOM Ready ──────────────────────────────
// Track whether we've received at least one stats update
let _statsReceived = false;
let _statsWaitTimeout = null;

function handleContainersTabActivation() {
  if (localStorage.getItem('qm-inspector-expanded') === 'true') {
    document.body.classList.add('inspector-expanded');
  }
  const panelOpen = localStorage.getItem('qm-bottom-panel-open');
  if (panelOpen !== '0') {
    openBottomPanel();
  }
  const panel = document.getElementById('bottom-panel');
  if (panel?.classList.contains('is-expanded')) {
    document.body.classList.add('bottom-panel-expanded');
  }
  if (window.editor) {
    window.editor.layout();
  }
}

function handleMonitorTabActivation() {
  if (state.cpuHistoryChart) state.cpuHistoryChart.resize();
  if (state.memHistoryChart) state.memHistoryChart.resize();
  loadMonitorCharts(state._monitorChartMinutes || 15);
  refreshMonitoringServerDropdown();
}

// The select's hx-trigger="load" fires while the Monitor pane is still
// display:none, where HTMX event timing is unreliable (issue #86, same
// workaround as refreshSshKeyDropdown). Refetch when the pane becomes
// visible, but only while the list is still empty: unlike the SSH key
// dropdown, refetching here would replace the options under a live
// selection.
function refreshMonitoringServerDropdown() {
  const sel = document.getElementById('monitoring-server-select');
  if (sel && sel.options.length <= 1) {
    htmx.ajax('GET', '/api/servers/options', {target: sel, swap: 'innerHTML'});
  }
}

function updateNavItemActive(tabId) {
  document.querySelectorAll('.nav-item').forEach(function(btn) {
    if (btn.dataset.tab === tabId) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
}

function switchTab(tabId) {
  localStorage.setItem('qm-active-tab', tabId);
  document.body.className = 'view-' + tabId;
  syncInspectorToggleBtn();
  updateNavItemActive(tabId);

  if (tabId === 'settings') {
    refreshSshKeyDropdown();
  } else if (tabId === 'containers') {
    // Restores bottom-panel-expanded body class if panel is expanded
    handleContainersTabActivation();
  } else if (tabId === 'monitor') {
    handleMonitorTabActivation();
  }
}

// ── SSH Key Dropdown Refresh ──────────────────────────────
// The hx-trigger="load" on the select fires once at DOMContentLoaded when the
// settings pane is display:none, making HTMX event-timing unreliable. Refresh
// explicitly whenever the dropdown becomes visible instead (issue #86).
function refreshSshKeyDropdown() {
  const sel = document.querySelector('select[name="ssh_key_id"]');
  if (sel) htmx.ajax('GET', '/api/keys/options', {target: sel, swap: 'innerHTML'});
}

// ── Settings Section Switcher ─────────────────────────────
function showSettingsSection(name) {
  document.querySelectorAll('.settings-group').forEach(function(g) {
    g.style.display = g.dataset.group === name ? 'grid' : 'none';
  });
  document.querySelectorAll('.settings-sidenav-item').forEach(function(btn) {
    const isActive = btn.dataset.section === name;
    btn.classList.toggle('active', isActive);
    if (isActive) {
      btn.setAttribute('aria-current', 'true');
    } else {
      btn.removeAttribute('aria-current');
    }
  });
  if (name === 'servers') refreshSshKeyDropdown();
  if (name !== 'themes') clearThemePreview();
  if (name === 'themes') initDensityRadio();
  if (name === 'themes') initEditorThemeRadio();
}

// ── Delegated Action Dispatch ─────────────────────────────
// Delegated click dispatch replacing inline handlers (issue #392).
const delegatedActions = {
  'switch-tab': function(btn) {
    switchTab(btn.dataset.tab);
  },
  'show-settings-section': function(btn) {
    showSettingsSection(btn.dataset.section);
  },
  'switch-bottom-tab': function(btn) {
    switchBottomTab(btn.dataset.pane);
  },
  'connect-terminal': function() {
    connectTerminal();
  },
  'tail-logs': function() {
    tailLogsFromPanel();
  },
  'toggle-bottom-panel-expand': function() {
    toggleBottomPanelExpand();
  },
  'toggle-bottom-panel': function() {
    toggleBottomPanel();
  },
  'session-add-new': function() {
    sessionAddNew();
  },
  'load-monitor-charts': function(btn) {
    loadMonitorCharts(Number(btn.dataset.minutes), btn);
  },
  // .catch( is a no-op because the error message has already been rendered into #validation-results by the time the promise rejects
  'validate-quadlet': function() {
    validateQuadlet().catch(function() {});
  },
  'save-quadlet': function() {
    saveQuadlet();
  },
  'toggle-inspector-expand': function() {
    toggleInspectorExpand();
  },
  'toggle-theme': function() {
    toggleTheme();
  },
  'toggle-profile-menu': function() {
    toggleProfileMenu();
  },
  'soft-refresh': function() {
    softRefresh();
  },
};

document.addEventListener('click', function(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  if (!Object.hasOwn(delegatedActions, action)) return;
  Reflect.get(delegatedActions, action)(btn);
});

const delegatedChangeActions = {
  'select-monitoring-server': function(elt) {
    selectMonitoringServer(elt.value);
  },
};

document.addEventListener('change', function(e) {
  const elt = e.target.closest('[data-action]');
  if (!elt) return;
  const action = elt.dataset.action;
  if (!Object.hasOwn(delegatedChangeActions, action)) return;
  Reflect.get(delegatedChangeActions, action)(elt);
});

const delegatedInputActions = {
  'filter-monitor-containers': function(elt) {
    applyContainerFilter(elt.value);
  },
};

document.addEventListener('input', function(e) {
  const elt = e.target.closest('[data-action]');
  if (!elt) return;
  const action = elt.dataset.action;
  if (!Object.hasOwn(delegatedInputActions, action)) return;
  Reflect.get(delegatedInputActions, action)(elt);
});

// ── Inspector Expand / Collapse Toggle ───────────────────
function syncInspectorToggleBtn() {
  const btn = document.getElementById('inspector-expand-btn');
  if (!btn) return;
  const expanded = document.body.classList.contains('inspector-expanded');
  btn.title = expanded ? 'Restore inspector' : 'Collapse inspector';
  btn.setAttribute('aria-label', btn.title);
}

function toggleInspectorExpand() {
  const expanded = document.body.classList.toggle('inspector-expanded');
  localStorage.setItem('qm-inspector-expanded', expanded ? 'true' : 'false');
  syncInspectorToggleBtn();
  // Monaco must re-layout after the inspector width changes
  if (window.editor) window.editor.layout();
}

// ── Monitoring Server Selector ────────────────────────────
function showMonitoringEmptyState(emptyEl, contentEl) {
  if (emptyEl) emptyEl.style.display = '';
  if (contentEl) contentEl.style.display = 'none';
  const barEl = document.getElementById('monitor-stat-bar');
  if (barEl) barEl.style.display = 'none';
  state._monitoringServerId = null;
}

function renderMonitoringServerStats(numId) {
  const cached = Reflect.get(lastStatsPerServer, numId);
  if (cached) {
    updateMonitoringView(cached);
    loadMonitorCharts(state._monitorChartMinutes || 15);
  } else {
    const tableEl = document.getElementById('monitoring-stats-table');
    if (tableEl) {
      tableEl.textContent = '';
      tableEl.appendChild(el('div', { className: 'p-4 text-muted italic' }, 'Waiting for stats data...'));
    }
    // `typeof` guard, as at the chart-theme sweep above: monitoringChart is
    // never assigned in this file. Until the dropdown was fed from the
    // database this branch was unreachable, because a server only had an
    // option once its stats had arrived (issue #365).
    if (typeof monitoringChart !== 'undefined' && monitoringChart) {
      monitoringChart.data.labels = [];
      monitoringChart.data.datasets[0].data = [];
      monitoringChart.data.datasets[1].data = [];
      monitoringChart.update();
    }
  }
}

// Re-apply the Monitor's server selection to a freshly swapped option list.
// Gated on the option existing, never on lastStatsPerServer having an entry:
// renderMonitoringServerStats already shows "Waiting for stats data..." for a
// server that has not reported yet.
function restoreMonitoringServerSelection(select) {
  let target = state._monitoringServerId ? String(state._monitoringServerId) : '';
  if (!target) {
    try {
      target = localStorage.getItem('qm-monitor-server') || '';
    } catch {
      // Ignore localStorage restrictions
    }
  }
  if (!target) return;

  const hasOption = Array.from(select.options).some(function(o) { return o.value === target; });
  if (!hasOption) return;

  select.value = target;

  // Assigning .value fires no change event, and none should be dispatched: on
  // a reload-servers swap of an unchanged selection this only has to restore
  // the visible value, not repaint the pane.
  if (String(state._monitoringServerId) !== target) {
    selectMonitoringServer(target);
  }
}

function selectMonitoringServer(serverId) {
  try {
    localStorage.setItem('qm-monitor-server', serverId ? String(serverId) : '');
  } catch {
    // Ignore localStorage restrictions
  }
  const numId = Number.parseInt(serverId, 10);
  const emptyEl = document.getElementById('monitoring-empty-state');
  const contentEl = document.getElementById('monitoring-content');

  if (!numId) {
    showMonitoringEmptyState(emptyEl, contentEl);
    return;
  }

  if (emptyEl) emptyEl.style.display = 'none';
  if (contentEl) contentEl.style.display = '';

  state._monitoringServerId = numId;

  renderMonitoringServerStats(numId);
}

// The Monitor's name filter is a lowercase substring match, applied to the
// container list and to the merged row list alike so the table, the charts and
// the glance bar always narrow over the same names.
function applyMonitorFilter(list) {
  if (!state.monitorContainerFilter) return list;
  return list.filter(function(c) {
    return (c.name || '').toLowerCase().includes(state.monitorContainerFilter);
  });
}

function updateMonitoringView(data) {
  // Only render when this data is for the server currently selected in the dropdown.
  if (data.server_id !== state._monitoringServerId) return;

  // Apply the active filter to every part of the pane: table, charts and the
  // glance bar all narrow together, so the numbers always describe what is
  // on screen.
  const allContainers = data.containers || [];
  const containers = applyMonitorFilter(allContainers);

  // The table shows one row per unit, including stopped units that have no
  // running container, so it renders merged rows. The charts and summary
  // strip only have real measurements to plot, so they keep using the real
  // containers list; a placeholder row would draw a flat-zero chart series
  // and drag the CPU/MEM totals down to a false 0.0%.
  const allRows = mergeUnitRows(allContainers, data.units);
  const rows = applyMonitorFilter(allRows);

  const paneData = function(list) {
    return { server_id: data.server_id, server_name: data.server_name, containers: list, units: data.units };
  };

  // Render the table, summary strip and filter count before touching the
  // charts: handleStatsUpdate catches a throw from the chart append below,
  // so the data render must not depend on it succeeding or the pane freezes.
  renderContainerStatsTable('monitoring-stats-table', paneData(rows));
  updateSummaryStrip(paneData(containers));
  updateFilterCount(rows.length, allRows.length);

  // Append the latest SSE data point to the live time-series charts.
  if ((state.cpuHistoryChart || state.memHistoryChart) && allContainers.length > 0) {
    const now = new Date();
    const timeLabel = now.getHours().toString().padStart(2, '0') + ':' +
                    now.getMinutes().toString().padStart(2, '0') + ':' +
                    now.getSeconds().toString().padStart(2, '0');
    const windowSec = (state._monitorChartMinutes || 15) * 60;

    const appendToChart = function(chart, valueKey) {
      if (!chart) return;
      // Drop datasets for containers the filter no longer matches; otherwise a
      // series drawn before the filter was typed stays on the canvas with
      // nothing appending to it, since this path never refetches history.
      // Chart.js controllers hold dataset indexes, so when a dataset is
      // removed the chart must re-sync before any push into a surviving
      // dataset, or the stale controller throws on the now-shifted index.
      const visibleNames = {};
      containers.forEach(function(c) { visibleNames[c.name] = true; });
      const datasetCountBeforeFilter = chart.data.datasets.length;
      chart.data.datasets = chart.data.datasets.filter(function(ds) { return visibleNames[ds.label]; });
      if (chart.data.datasets.length !== datasetCountBeforeFilter) {
        chart.update('none');
      }

      // Build a map of current dataset labels for quick lookup
      const datasetByName = {};
      chart.data.datasets.forEach(function(ds) { datasetByName[ds.label] = ds; });

      containers.forEach(function(c) {
        const val = valueKey === 'cpu' ? parsePercent(c.cpu) : parsePercent(c.mem);
        if (datasetByName[c.name]) {
          datasetByName[c.name].data.push(val);
        } else {
          // New container not yet in chart — add a new dataset
          const color = chartColorFor(c.name);
          chart.data.datasets.push({
            label: c.name,
            data: [val],
            borderColor: color,
            backgroundColor: color.replace('1)', '0.08)'),
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            spanGaps: false,
          });
        }
      });

      // Append the shared time label and trim old data outside the window
      chart.data.labels.push(timeLabel);
      // Trim from the front while the window is exceeded
      while (chart.data.labels.length > windowSec / 5 + 10) {
        chart.data.labels.shift();
        chart.data.datasets.forEach(function(ds) { ds.data.shift(); });
      }

      applyChartSelection(chart);
      chart.update('none');
    }

    appendToChart(state.cpuHistoryChart, 'cpu');
    appendToChart(state.memHistoryChart, 'mem');
  }
}

// "N of M shown" next to the filter box. Both counts come from the running
// container list, so this reports what the table and charts are showing and
// not the stopped containers the glance bar also counts.
function updateFilterCount(shown, total) {
  const el = document.getElementById('monitor-filter-count');
  if (!el) return;

  if (!state.monitorContainerFilter) {
    el.hidden = true;
    el.textContent = '';
    return;
  }

  el.textContent = shown + ' of ' + total + ' shown';
  el.hidden = false;
}

function applyContainerFilter(value) {
  // The filter decides which containers are available, so a filter change
  // resets which of them are selected, otherwise the user can end up with
  // an empty chart and no visible reason.
  monitorChartSelection.clear();
  state.monitorContainerFilter = (value || '').toLowerCase().trim();
  const serverId = state._monitoringServerId;
  const cached = Reflect.get(lastStatsPerServer, serverId);
  if (serverId && cached) {
    updateMonitoringView(cached);
  }
}

function computeServerTotals(containers) {
  const list = containers || [];
  const totals = { cpu: 0, mem: 0 };
  list.forEach(function(c) {
    totals.cpu += parsePercent(c.cpu);
    totals.mem += parsePercent(c.mem);
  });
  return totals;
}

// U+2014 EM DASH: the "nothing reported yet" placeholder, matching what the
// stats engine sends for container fields it could not read.
const STAT_PLACEHOLDER = '\u2014';

// Units are the source of truth for the fleet counts; containers only supply
// health and load. A server that has not reported units yet shows placeholders
// rather than a misleading zero.
function computeUnitCounts(units) {
  if (units === undefined || units === null) {
    return {
      total: STAT_PLACEHOLDER,
      running: STAT_PLACEHOLDER,
      stopped: STAT_PLACEHOLDER,
      failed: STAT_PLACEHOLDER
    };
  }
  // Units are matched against the same lowercase substring filter used for
  // container names, keyed off the unit stem (name without ".service").
  const filteredUnits = units.filter(function(u) {
    const stem = (u.unit || '').replace(/\.service$/, '').toLowerCase();
    return !state.monitorContainerFilter || stem.includes(state.monitorContainerFilter);
  });
  const total = filteredUnits.length;
  const running = filteredUnits.filter(function(u) { return u.active_state === 'active'; }).length;
  // A failed unit is not simply "stopped": stopped stays total - running so the
  // three load counts still add up, and failed overlaps it as its own signal.
  const failed = filteredUnits.filter(function(u) { return u.active_state === 'failed'; }).length;
  return { total: total, running: running, stopped: total - running, failed: failed };
}

// The 'danger' class carries the unhealthy state by colour alone, so repeat it
// as a glyph for anyone who cannot perceive that.
function renderUnhealthyStat(unhealthy) {
  const elUnhealthy = document.getElementById('mstat-unhealthy');
  if (!elUnhealthy) return;
  elUnhealthy.textContent = unhealthy;
  elUnhealthy.classList.toggle('danger', unhealthy > 0);
  if (unhealthy > 0) {
    const flag = document.createElement('span');
    flag.className = 'monitor-stat-flag';
    flag.setAttribute('aria-hidden', 'true');
    flag.textContent = '⚠';
    elUnhealthy.appendChild(flag);
  }
}

// Same colour-plus-glyph treatment as the unhealthy stat, for the same reason.
function renderFailedStat(failed) {
  const elFailed = document.getElementById('mstat-failed');
  if (!elFailed) return;
  elFailed.textContent = failed;
  elFailed.classList.toggle('danger', failed > 0);
  if (failed > 0) {
    const flag = document.createElement('span');
    flag.className = 'monitor-stat-flag';
    flag.setAttribute('aria-hidden', 'true');
    flag.textContent = '\u26a0';
    elFailed.appendChild(flag);
  }
}

function healthAnnouncement(unhealthy) {
  if (unhealthy === 0) return 'All containers healthy';
  if (unhealthy === 1) return '1 container unhealthy';
  return unhealthy + ' containers unhealthy';
}

// Only rewrite the live region's text when the unhealthy count actually
// changes, so unchanged SSE ticks do not re-announce the same state.
function announceHealthChange(unhealthy) {
  if (unhealthy === lastAnnouncedUnhealthy) return;
  const elHealthStatus = document.getElementById('monitor-health-status');
  if (elHealthStatus) {
    elHealthStatus.textContent = healthAnnouncement(unhealthy);
  }
  lastAnnouncedUnhealthy = unhealthy;
}

function updateSummaryStrip(data) {
  const containers = data.containers || [];
  const counts = computeUnitCounts(data.units);
  const unhealthy = containers.filter(function(c) {
    return c.health && c.health !== 'healthy';
  }).length;
  const totals = computeServerTotals(containers);
  const hasLoad = containers.length > 0;

  setStatText('mstat-total', counts.total);
  setStatText('mstat-running', counts.running);
  setStatText('mstat-stopped', counts.stopped);
  renderUnhealthyStat(unhealthy);
  renderFailedStat(counts.failed);
  setStatText('mstat-cpu', hasLoad ? totals.cpu.toFixed(1) + '%' : STAT_PLACEHOLDER);
  setStatText('mstat-mem', hasLoad ? totals.mem.toFixed(1) + '%' : STAT_PLACEHOLDER);

  const elBar = document.getElementById('monitor-stat-bar');
  if (elBar) elBar.style.display = '';

  announceHealthChange(unhealthy);
}

// ── Terminal Session Management ──────────────────────────
function loadFitAddon(callback) {
    callback();
}

// Sessions strip (#terminal-conn-tabs) is shared by terminal and log chips, so its
// .has-tabs visibility must reflect both maps, not just whichever kind changed.
function refreshSessionsStripVisibility() {
    const tabsEl = document.getElementById('terminal-conn-tabs');
    if (!tabsEl) return;
    const hasAny = window._terminalTabs.size > 0 || window._logTabs.size > 0;
    tabsEl.classList.toggle('has-tabs', hasAny);
}

function hideTerminalSection() {
    // Terminals are user-managed; auto-closing on deselect removed.
}

function showTerminalMessage(msg) {
    const hint = document.getElementById('terminal-empty-hint');
    if (hint) {
        hint.textContent = msg;
        hint.style.display = '';
        setTimeout(function() {
            if (hint.textContent === msg) {
                hint.textContent = 'Select a running container and click Connect';
            }
        }, 3000);
    }
}

// ── Bottom Panel Management ───────────────────────────────
function openBottomPanel(tab) {
    const panel = document.getElementById('bottom-panel');
    if (!panel) return;
    panel.classList.remove('is-collapsed');
    const body = panel.querySelector('.bottom-panel-body');
    const handle = document.getElementById('bottom-panel-resize-handle');
    if (body) body.classList.remove('hidden');
    if (handle) handle.classList.remove('hidden');
    localStorage.setItem('qm-bottom-panel-open', '1');
    if (tab) switchBottomTab(tab);
    const key = state._activeTerminalTabKey;
    if (key) {
        const session = window._terminalTabs.get(key);
        if (session?.fitAddon) session.fitAddon.fit();
    }
}

function fitActiveTerminal() {
    const key = state._activeTerminalTabKey;
    if (!key) return;
    const session = window._terminalTabs.get(key);
    if (session?.fitAddon) {
        session.fitAddon.fit();
    }
}

function toggleBottomPanel() {
    const panel = document.getElementById('bottom-panel');
    if (!panel) return;
    const isCollapsed = panel.classList.toggle('is-collapsed');
    const body = panel.querySelector('.bottom-panel-body');
    const handle = document.getElementById('bottom-panel-resize-handle');
    if (body) body.classList.toggle('hidden', isCollapsed);
    if (handle) handle.classList.toggle('hidden', isCollapsed);
    localStorage.setItem('qm-bottom-panel-open', isCollapsed ? '0' : '1');
    if (!isCollapsed) {
        fitActiveTerminal();
    }
}

function toggleBottomPanelExpand() {
    const panel = document.getElementById('bottom-panel');
    if (!panel) return;
    const expanded = panel.classList.toggle('is-expanded');
    document.body.classList.toggle('bottom-panel-expanded', expanded);
    localStorage.setItem('qm-bottom-panel-expanded', expanded ? '1' : '0');
    const btn = document.getElementById('bottom-panel-expand-btn');
    if (btn) {
        btn.title = expanded ? 'Align with editor' : 'Expand panel to full width';
        btn.setAttribute('aria-label', btn.title);
    }
    const key = state._activeTerminalTabKey;
    if (key) {
        const session = window._terminalTabs.get(key);
        if (session?.fitAddon) session.fitAddon.fit();
    }
}

function switchBottomTab(pane) {
    try {
        localStorage.setItem('qm-bottom-tab', pane);
    } catch {
        // Ignore localStorage restrictions
    }
    document.querySelectorAll('.bottom-tab').forEach(function(btn) {
        const isActive = btn.dataset.pane === pane;
        btn.classList.toggle('is-active', isActive);
        btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    document.querySelectorAll('.bottom-pane').forEach(function(p) {
        p.classList.toggle('hidden', p.id !== 'bottom-' + pane + '-pane');
    });
    const controls = document.querySelector('.terminal-controls');
    if (controls) controls.classList.toggle('hidden', pane !== 'terminal');
    const logsControls = document.querySelector('.logs-controls');
    if (logsControls) logsControls.classList.toggle('hidden', pane !== 'logs');
    document.querySelectorAll('.terminal-conn-tab, .log-conn-tab').forEach(function(el) {
        el.classList.remove('is-active');
    });
    if (pane === 'terminal') {
        const key = state._activeTerminalTabKey;
        if (key) {
            document.querySelectorAll('.terminal-conn-tab').forEach(function(el) {
                el.classList.toggle('is-active', el.dataset.key === key);
            });
            const session = window._terminalTabs.get(key);
            if (session?.fitAddon) {
                setTimeout(function() { session.fitAddon.fit(); }, 50);
            }
        }
    } else if (pane === 'logs') {
        const logKey = state._activeLogTabKey;
        if (logKey) {
            document.querySelectorAll('.log-conn-tab').forEach(function(el) {
                el.classList.toggle('is-active', el.dataset.key === logKey);
            });
        }
    }
}

function findActualRunningContainerName(running, stem) {
    let actualName = null;
    running.forEach(function(name) {
        if (name.includes(stem) || stem.includes(name)) {
            actualName = name;
        }
    });
    return actualName;
}

function getTerminalShellCommand() {
    const shellSelect = document.getElementById('terminal-shell-select');
    const shell = shellSelect ? shellSelect.value : 'bash';
    if (shell === 'custom') {
        const customInput = document.getElementById('terminal-custom-cmd-input');
        return (customInput ? customInput.value.trim() : '') || 'bash';
    }
    return shell;
}

function connectTerminal() {
    const stem = state._selectedContainerStem;
    const serverId = state._selectedContainerServerId;
    const scope = state._selectedContainerScope || 'global';
    if (!stem || !serverId) {
        showTerminalMessage('Select a container from the sidebar first.');
        return;
    }

    const running = Reflect.get(runningContainersBySid, serverId) || new Set();
    const actualContainerName = findActualRunningContainerName(running, stem);

    if (!actualContainerName) {
        showTerminalMessage('Container must be running to open a terminal.');
        return;
    }

    const tabKey = serverId + ':' + actualContainerName;

    // Already open → just switch to it
    if (window._terminalTabs.has(tabKey)) {
        openBottomPanel('terminal');
        switchTerminalTab(tabKey);
        return;
    }

    const cmd = getTerminalShellCommand();
    if (!cmd) {
        showTerminalMessage('Enter a command first.');
        return;
    }

    openBottomPanel('terminal');
    loadFitAddon(function() {
        createTerminalTab(tabKey, serverId, actualContainerName, cmd, scope);
    });
}

function createTerminalTab(tabKey, serverId, containerName, cmd, scope) {
    const cached = Reflect.get(lastStatsPerServer, serverId);
    const serverName = cached?.server_name
        || ('srv-' + serverId);
    const label = serverName + ':' + containerName;

    // ── Tab button ──────────────────────────────────────
    const tabEl = document.createElement('button');
    tabEl.className = 'terminal-conn-tab';
    tabEl.dataset.key = tabKey;
    tabEl.setAttribute('title', label);

    const labelSpan = document.createElement('span');
    labelSpan.className = 'terminal-conn-tab-label';
    labelSpan.textContent = label;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'terminal-conn-tab-close';
    closeBtn.setAttribute('aria-label', 'Close ' + label);
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        closeTerminalTab(tabKey);
    });

    tabEl.appendChild(labelSpan);
    tabEl.appendChild(closeBtn);
    tabEl.addEventListener('click', function() { switchTerminalTab(tabKey); });

    const tabsEl = document.getElementById('terminal-conn-tabs');
    if (tabsEl) {
        tabsEl.appendChild(tabEl);
        tabsEl.classList.add('has-tabs');
    }

    // ── xterm pane div ──────────────────────────────────
    const paneEl = document.createElement('div');
    paneEl.className = 'terminal-tab-pane hidden';
    paneEl.dataset.key = tabKey;

    const xtermDiv = document.createElement('div');
    xtermDiv.className = 'xterm-container';
    paneEl.appendChild(xtermDiv);

    const bodyEl = document.getElementById('terminal-tabs-body');
    if (bodyEl) bodyEl.appendChild(paneEl);

    // Hide empty hint
    const hint = document.getElementById('terminal-empty-hint');
    if (hint) hint.style.display = 'none';

    // Toggle DOM visibility BEFORE creating xterm to avoid 0x0 size calculation
    window._terminalTabs.set(tabKey, { tabEl: tabEl, paneEl: paneEl, serverId: serverId, containerName: containerName, scope: scope, cmd: cmd });
    switchTerminalTab(tabKey);

    // ── xterm instance ──────────────────────────────────
    const term = new Terminal({ rows: 24, cols: 80, cursorBlink: true });
    term.open(xtermDiv);

    const fitAddon = new window.FitAddon.FitAddon();
    term.loadAddon(fitAddon);

    // ── WebSocket ───────────────────────────────────────
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = protocol + '//' + window.location.host
        + '/ws/exec/' + serverId + '/' + encodeURIComponent(containerName)
        + '?scope=' + encodeURIComponent(scope) + '&cmd=' + encodeURIComponent(cmd);
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';

    ws.onopen = function() {
        fitAddon.fit();
        const dims = fitAddon.proposeDimensions();
        ws.send(JSON.stringify({
            type: 'resize',
            cols: dims ? dims.cols : 80,
            rows: dims ? dims.rows : 24
        }));
        term.onData(function(data) {
            if (ws.readyState === WebSocket.OPEN) ws.send(data);
        });
    };

    ws.onmessage = function(e) {
        term.write(e.data instanceof ArrayBuffer ? new Uint8Array(e.data) : e.data);
    };

    ws.onerror = function() {
        term.write('\r\n\u001b[31mConnection error\u001b[0m\r\n');
    };

    ws.onclose = function(evt) {
        if (evt?.code === 4403) {
            term.write('\r\n\u001b[31m[terminal access requires the editor role]\u001b[0m\r\n');
        } else {
            term.write('\r\n\u001b[2m[session closed]\u001b[0m\r\n');
        }
        tabEl.classList.add('is-disconnected');
    };

    window._terminalTabs.set(tabKey, { term: term, ws: ws, fitAddon: fitAddon, tabEl: tabEl, paneEl: paneEl, serverId: serverId, containerName: containerName, scope: scope, cmd: cmd });

    setTimeout(function() {
        if (ws.readyState === WebSocket.OPEN) {
            fitAddon.fit();
        }
        term.focus();
    }, 10);
}

function switchTerminalTab(key) {
    state._activeTerminalTabKey = key;

    document.querySelectorAll('.terminal-conn-tab, .log-conn-tab').forEach(function(el) {
        el.classList.remove('is-active');
    });
    document.querySelectorAll('.terminal-conn-tab').forEach(function(el) {
        el.classList.toggle('is-active', el.dataset.key === key);
    });
    document.querySelectorAll('.terminal-tab-pane').forEach(function(el) {
        el.classList.toggle('hidden', el.dataset.key !== key);
    });

    switchBottomTab('terminal');

    const session = window._terminalTabs.get(key);
    if (session?.fitAddon) {
        setTimeout(function() { session.fitAddon.fit(); }, 50);
    }
}

function disposeTerminalSession(session) {
    if (session.ws && session.ws.readyState !== WebSocket.CLOSED) {
        session.ws.close();
    }
    try { session.term.dispose(); } catch { /* xterm may throw if initialized on a hidden element */ }
}

function removeTerminalDOM(session) {
    session.tabEl?.remove();
    session.paneEl?.remove();
}

function handleClosedTabFallback(key) {
    if (window._terminalTabs.size === 0) {
        const hint = document.getElementById('terminal-empty-hint');
        if (hint) hint.style.display = '';
        state._activeTerminalTabKey = null;
    } else if (state._activeTerminalTabKey === key) {
        switchTerminalTab(window._terminalTabs.keys().next().value);
    }
    refreshSessionsStripVisibility();
}

function closeTerminalTab(key) {
    const session = window._terminalTabs.get(key);
    if (!session) return;

    disposeTerminalSession(session);
    removeTerminalDOM(session);

    window._terminalTabs.delete(key);
    handleClosedTabFallback(key);
}

function sessionAddNew() {
    const activeTab = document.querySelector('.bottom-tab.is-active');
    const pane = activeTab ? activeTab.dataset.pane : 'terminal';
    if (pane === 'logs') {
        tailLogsFromPanel();
    } else {
        connectTerminal();
    }
}

// Handle shell selector changes (setup after DOM is ready)
const setupShellSelector = function() {
    const shellSelect = document.getElementById('terminal-shell-select');
    if (shellSelect) {
        shellSelect.addEventListener('change', function() {
            const customRow = document.getElementById('terminal-custom-cmd-row');
            if (this.value === 'custom' && customRow) {
                customRow.classList.remove('hidden');
            } else if (customRow) {
                customRow.classList.add('hidden');
            }
        });
    }
};

// Handle log time-range selector changes (setup after DOM is ready)
const setupLogSinceSelector = function() {
    const sinceSelect = document.getElementById('log-since-select');
    if (sinceSelect) {
        sinceSelect.addEventListener('change', function() {
            const value = this.value;
            try {
                localStorage.setItem('qm-log-since-range', value);
            } catch {
                // Ignore localStorage restrictions
            }

            const key = state._activeLogTabKey;
            const entry = key ? window._logTabs.get(key) : null;
            if (!entry) return;

            entry.since = value;
            if (entry.ws) entry.ws.close();
            if (entry.logDiv) entry.logDiv.textContent = 'Reconnecting…\n';
            openLogSocket(key);
        });
    }
};

// Ctrl+1 / Ctrl+2 — switch bottom panel tabs when panel is open
document.addEventListener('keydown', function(e) {
    if (!e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    const panel = document.getElementById('bottom-panel');
    if (!panel || panel.classList.contains('is-collapsed')) return;
    if (e.key === '1') { e.preventDefault(); switchBottomTab('terminal'); }
    else if (e.key === '2') { e.preventDefault(); switchBottomTab('logs'); }
});

// ── Global window resize handler for the active terminal tab ────────────────
window.addEventListener('resize', function() {
    const key = state._activeTerminalTabKey;
    if (!key) return;
    const session = window._terminalTabs.get(key);
    if (!session?.fitAddon) return;
    session.fitAddon.fit();
    if (session.ws?.readyState === WebSocket.OPEN) {
        const dims = session.fitAddon.proposeDimensions();
        session.ws.send(JSON.stringify({
            type: 'resize',
            cols: dims ? dims.cols : 80,
            rows: dims ? dims.rows : 24
        }));
    }
});

// ── Resizable Panel Handles ──────────────────────────────
function initResizableHandles() {
    const SIDEBAR_MIN = 180, SIDEBAR_MAX = 500;
    const INSPECTOR_MIN = 220, INSPECTOR_MAX = 900;
    const SETTINGS_SIDENAV_MIN = 160, SETTINGS_SIDENAV_MAX = 480;
    const BOTTOM_PANEL_MIN = 100, BOTTOM_PANEL_MAX = Math.floor(window.innerHeight * 0.75);

    function makeDraggable(handleEl, cssVar, storageKey, minPx, maxPx, getInitialPx) {
        if (!handleEl) return;

        handleEl.addEventListener('mousedown', function(e) {
            e.preventDefault();
            const startX = e.clientX;
            const startPx = getInitialPx();

            handleEl.classList.add('dragging');
            document.body.classList.add('is-resizing');

            function onMove(e) {
                const delta = e.clientX - startX;
                const newPx = Math.min(maxPx, Math.max(minPx, startPx + delta));
                document.documentElement.style.setProperty(cssVar, newPx + 'px');
            }

            function onUp() {
                handleEl.classList.remove('dragging');
                document.body.classList.remove('is-resizing');
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);

                // Persist width to localStorage
                const finalPx = getComputedStyle(document.documentElement)
                    .getPropertyValue(cssVar).trim();
                localStorage.setItem(storageKey, finalPx);

                // Re-layout Monaco if open
                if (window.editor) window.editor.layout();
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    // Left handle: controls sidebar width
    makeDraggable(
        document.getElementById('resize-handle-left'),
        '--sidebar-width',
        'qm-sidebar-width',
        SIDEBAR_MIN, SIDEBAR_MAX,
        function() {
            const sidebar = document.getElementById('navigator');
            return sidebar ? sidebar.getBoundingClientRect().width : 300;
        }
    );

    // Settings sidenav handle: controls settings sidebar width
    makeDraggable(
        document.getElementById('settings-sidenav-resize-handle'),
        '--settings-sidenav-width',
        'qm-settings-sidenav-width',
        SETTINGS_SIDENAV_MIN, SETTINGS_SIDENAV_MAX,
        function() {
            const sn = document.querySelector('.settings-sidenav');
            return sn ? sn.getBoundingClientRect().width : 220;
        }
    );

    // Right handle: controls inspector width (drag left = bigger inspector)
    const rightHandle = document.getElementById('resize-handle-right');
    if (rightHandle) {
        rightHandle.addEventListener('mousedown', function(e) {
            e.preventDefault();
            const startX = e.clientX;
            const inspector = document.getElementById('inspector');
            const startPx = inspector ? inspector.getBoundingClientRect().width : 320;

            rightHandle.classList.add('dragging');
            document.body.classList.add('is-resizing');

            function onMove(e) {
                const delta = startX - e.clientX;   // dragging left widens inspector
                const newPx = Math.min(INSPECTOR_MAX, Math.max(INSPECTOR_MIN, startPx + delta));
                document.documentElement.style.setProperty('--inspector-width', newPx + 'px');
            }

            function onUp() {
                rightHandle.classList.remove('dragging');
                document.body.classList.remove('is-resizing');
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                const finalPx = getComputedStyle(document.documentElement)
                    .getPropertyValue('--inspector-width').trim();
                localStorage.setItem('qm-inspector-width', finalPx);
                if (window.editor) window.editor.layout();
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    // Bottom panel handle: drag up = taller panel
    const bottomHandle = document.getElementById('bottom-panel-resize-handle');
    if (bottomHandle) {
        bottomHandle.addEventListener('mousedown', function(e) {
            e.preventDefault();
            const startY = e.clientY;
            const panel = document.getElementById('bottom-panel');
            const startH = panel ? panel.getBoundingClientRect().height : 300;

            bottomHandle.classList.add('dragging');
            document.body.classList.add('is-resizing');

            function onMove(e) {
                const delta = startY - e.clientY; // dragging up increases height
                const newH = Math.min(BOTTOM_PANEL_MAX, Math.max(BOTTOM_PANEL_MIN, startH + delta));
                document.documentElement.style.setProperty('--bottom-panel-height', newH + 'px');
                const _rk = state._activeTerminalTabKey;
                if (_rk) { const _rs = window._terminalTabs.get(_rk); if (_rs?.fitAddon) _rs.fitAddon.fit(); }
            }

            function onUp() {
                bottomHandle.classList.remove('dragging');
                document.body.classList.remove('is-resizing');
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                const finalH = getComputedStyle(document.documentElement)
                    .getPropertyValue('--bottom-panel-height').trim();
                localStorage.setItem('qm-bottom-panel-height', finalH);
                const _uk = state._activeTerminalTabKey;
                if (_uk) { const _us = window._terminalTabs.get(_uk); if (_us?.fitAddon) _us.fitAddon.fit(); }
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }
}


document.addEventListener('DOMContentLoaded', function() {
// Restore persisted panel widths before first paint
(function restorePanelWidths() {
  const saved = {
    sidebar: localStorage.getItem('qm-sidebar-width'),
    inspector: localStorage.getItem('qm-inspector-width'),
    settingsSidenav: localStorage.getItem('qm-settings-sidenav-width'),
    bottomPanel: localStorage.getItem('qm-bottom-panel-height'),
  };
  if (saved.sidebar) document.documentElement.style.setProperty('--sidebar-width', saved.sidebar);
  if (saved.inspector) document.documentElement.style.setProperty('--inspector-width', saved.inspector);
  if (saved.settingsSidenav) document.documentElement.style.setProperty('--settings-sidenav-width', saved.settingsSidenav);
  if (saved.bottomPanel) document.documentElement.style.setProperty('--bottom-panel-height', saved.bottomPanel);
  if (localStorage.getItem('qm-bottom-panel-expanded') === '1') {
    const panel = document.getElementById('bottom-panel');
    if (panel) panel.classList.add('is-expanded');
    document.body.classList.add('bottom-panel-expanded');
  }
})();

switchTab(localStorage.getItem('qm-active-tab') || 'overview');
switchBottomTab(localStorage.getItem('qm-bottom-tab') || 'terminal');
initCpuChart();
initMemChart();
setupShellSelector();
setupLogSinceSelector();
try {
    const storedLogSince = localStorage.getItem('qm-log-since-range');
    const logSinceSelect = document.getElementById('log-since-select');
    if (storedLogSince && logSinceSelect) logSinceSelect.value = storedLogSince;
} catch {
    // Ignore localStorage restrictions
}
connectSSE();
fetchPollHealthSnapshot();
setInterval(function() {
  const pane = document.getElementById('monitoring-pane');
  if (pane && pane.offsetParent !== null) {
    fetchPollHealthSnapshot();
  }
}, 30000);
initResizableHandles();

// ── Reconnect Banner ──────────────────────────────────────
(function() {
    let pending = null;
    try {
        pending = JSON.parse(localStorage.getItem('qm-pending-reconnect'));
    } catch {
        // Ignore localStorage restrictions or parsing errors
    }
    if (!pending || (pending.terminals.length === 0 && (!pending.logTails || pending.logTails.length === 0))) return;
    localStorage.removeItem('qm-pending-reconnect');

    const parts = [];
    if (pending.terminals.length > 0) parts.push(pending.terminals.length + ' terminal' + (pending.terminals.length > 1 ? 's' : ''));
    if (pending.logTails && pending.logTails.length > 0) parts.push(pending.logTails.length + ' log tail' + (pending.logTails.length > 1 ? 's' : ''));

    const banner = el('div', { id: 'reconnect-banner', className: 'reconnect-banner' }, [
        el('span', { className: 'reconnect-banner-msg' }, 'You had ' + parts.join(' and ') + ' open before the last reload.'),
        el('button', { className: 'btn btn-sm btn-primary', id: 'reconnect-yes-btn' }, 'Reconnect'),
        el('button', { className: 'btn btn-sm btn-secondary', id: 'reconnect-no-btn' }, 'Dismiss')
    ]);

    const nav = document.querySelector('.top-nav');
    if (nav) nav.parentNode.insertBefore(banner, nav.nextSibling);

    document.getElementById('reconnect-no-btn').addEventListener('click', function() {
        banner.remove();
    });

    document.getElementById('reconnect-yes-btn').addEventListener('click', function() {
        banner.remove();
        if (pending.logTails && pending.logTails.length > 0) {
            openBottomPanel('logs');
            pending.logTails.forEach(function(l) {
                if (!window._logTabs.has(l.tabKey)) {
                    createLogTab(l.tabKey, l.serverId, l.unitName, l.scope);
                }
            });
        }
        if (pending.terminals.length > 0) {
            openBottomPanel('terminal');
            loadFitAddon(function() {
                pending.terminals.forEach(function(t) {
                    if (!window._terminalTabs.has(t.tabKey)) {
                        createTerminalTab(t.tabKey, t.serverId, t.containerName, t.cmd, t.scope);
                    }
                });
            });
        }
    });
})();

// If no stats arrive within 15s of page load, update the monitoring
// placeholder so the user isn't left staring at it forever.
_statsWaitTimeout = setTimeout(function() {
  if (!_statsReceived) {
    const monitoringTableEl = document.getElementById('monitoring-stats-table');
    if (monitoringTableEl) {
      monitoringTableEl.textContent = '';
      monitoringTableEl.appendChild(el('div', { className: 'p-4 text-warning italic' }, 'No stats received yet — verify server connectivity.'));
    }
  }
}, 15000);
    document.documentElement.dataset.appReady = '1';
});

// ── File Deletion ─────────────────────────────────────────
let _ctxMenu = null;

function showFileContextMenu(event, serverId, path, scope) {
    event.preventDefault();

    if (_ctxMenu) _ctxMenu.remove();

    const fileName = path.split('/').pop();
    const stem = fileName.replace(/\.[^.]+$/, '');
    const unitName = unitNameFor(fileName);
    const quadletType = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';
    const isPod = quadletType === 'pod';

    _ctxMenu = document.createElement('div');
    _ctxMenu.className = 'context-menu';
    _ctxMenu.style.cssText = 'position:fixed;left:' + event.clientX + 'px;top:' + event.clientY + 'px';

    const editBtn = document.createElement('button');
    editBtn.className = 'context-menu-item';
    editBtn.textContent = 'Edit';
    editBtn.onclick = function() {
        _ctxMenu.remove();
        _ctxMenu = null;
        const treeBtn = document.querySelector('.quadlet-tree-btn[data-server-id="' + serverId + '"][data-path="' + path + '"]');
        window.setSelectedQuadletBtn(treeBtn || null);
        window.setActiveServer(serverId);
        window.selectContainerStem(stem, serverId, scope, quadletType);
        htmx.ajax('GET', '/api/file/' + serverId + '?path=' + encodeURIComponent(path) + '&scope=' + encodeURIComponent(scope) + '&name=' + encodeURIComponent(fileName), {
            target: '#editor-pane',
            swap: 'outerHTML'
        });
        switchTab('containers');
    };
    _ctxMenu.appendChild(editBtn);

    const startBtn = document.createElement('button');
    startBtn.className = 'context-menu-item';
    startBtn.textContent = 'Start';
    startBtn.onclick = function() {
        _ctxMenu.remove();
        _ctxMenu = null;
        if (isPod) {
            htmx.ajax('POST', '/api/pod-action/' + serverId + '?action=start&pod_name=' + encodeURIComponent(stem) + '&scope=' + encodeURIComponent(scope), { swap: 'none' });
            return;
        }
        htmx.ajax('POST', '/api/systemctl/' + serverId + '?action=start&unit=' + encodeURIComponent(unitName) + '&scope=' + encodeURIComponent(scope) + '&quadlet_type=' + encodeURIComponent(quadletType), { swap: 'none' });
    };
    _ctxMenu.appendChild(startBtn);

    const stopBtn = document.createElement('button');
    stopBtn.className = 'context-menu-item';
    stopBtn.textContent = 'Stop';
    stopBtn.onclick = function() {
        _ctxMenu.remove();
        _ctxMenu = null;
        if (isPod) {
            htmx.ajax('POST', '/api/pod-action/' + serverId + '?action=stop&pod_name=' + encodeURIComponent(stem) + '&scope=' + encodeURIComponent(scope), { swap: 'none' });
            return;
        }
        htmx.ajax('POST', '/api/systemctl/' + serverId + '?action=stop&unit=' + encodeURIComponent(unitName) + '&scope=' + encodeURIComponent(scope) + '&quadlet_type=' + encodeURIComponent(quadletType), { swap: 'none' });
    };
    _ctxMenu.appendChild(stopBtn);

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'context-menu-item context-menu-danger';
    deleteBtn.textContent = 'Delete';
    deleteBtn.onclick = function() {
        _ctxMenu.remove();
        _ctxMenu = null;
        window.confirmDeleteFile(serverId, path, scope);
    };
    _ctxMenu.appendChild(deleteBtn);
    document.body.appendChild(_ctxMenu);

    setTimeout(function() {
        document.addEventListener('click', function closeMenu() {
            if (_ctxMenu) { _ctxMenu.remove(); _ctxMenu = null; }
            document.removeEventListener('click', closeMenu);
        }, { once: true });
    }, 0);
}

function confirmDeleteFile(serverId, path, scope) {
    const existing = document.getElementById('delete-confirm-modal');
    if (existing) existing.remove();

    const fileName = path.split('/').pop();

    const modal = document.createElement('div');
    modal.id = 'delete-confirm-modal';
    modal.className = 'modal-overlay';

    const content = document.createElement('div');
    content.className = 'modal-content';

    const h2 = document.createElement('h2');
    h2.className = 'panel-title mb-4';
    h2.textContent = 'Delete File';
    content.appendChild(h2);

    const p = document.createElement('p');
    p.className = 'text-sm mb-6';
    p.textContent = 'Delete ';
    const strong = document.createElement('strong');
    strong.textContent = fileName;
    p.appendChild(strong);
    p.appendChild(document.createTextNode('? This cannot be undone.'));
    content.appendChild(p);

    const btnContainer = document.createElement('div');
    btnContainer.className = 'flex justify-end space-x-2';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function() {
        modal.remove();
    });
    btnContainer.appendChild(cancelBtn);

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn btn-danger';
    deleteBtn.textContent = 'Delete';
    deleteBtn.addEventListener('click', function() {
        window.executeDeleteFile(serverId, path, scope);
    });
    btnContainer.appendChild(deleteBtn);

    content.appendChild(btnContainer);
    modal.appendChild(content);
    document.body.appendChild(modal);
    window.setupModalDismissal('delete-confirm-modal');
}

async function executeDeleteFile(serverId, path, scope) {
    document.getElementById('delete-confirm-modal')?.remove();

    const targetUrl = new URL('/api/files', window.location.origin);
    targetUrl.searchParams.set('server_id', serverId);
    targetUrl.searchParams.set('path', path);
    targetUrl.searchParams.set('scope', scope);

    if (targetUrl.origin !== window.location.origin || targetUrl.pathname !== '/api/files') {
        console.error('Security Error: Disallowed target URL');
        return;
    }

    const response = await fetch(targetUrl.toString(), {
        method: 'DELETE',
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    });
    const html = await response.text();

    const toast = document.getElementById('status-toast');
    if (toast) {
        toast.innerHTML = '';
        const parser = new window.DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const toastMsg = doc.querySelector('.toast-msg');
        if (toastMsg) {
            const div = document.createElement('div');
            div.className = toastMsg.className;
            div.textContent = toastMsg.textContent;
            toast.appendChild(div);
        }
    }

    if (response.headers.get('HX-Trigger') === 'reload-servers') {
        document.body.dispatchEvent(new Event('reload-servers'));
    }
}

// ── Real-time Logs WebSocket ─────────────────────────────
function showLogMessage(msg) {
    const hint = document.getElementById('log-empty-hint');
    if (hint) {
        hint.textContent = msg;
        hint.style.display = '';
        setTimeout(function() {
            if (hint.textContent === msg) {
                hint.textContent = 'Click "Tail Logs" to start streaming a container\'s logs';
            }
        }, 3000);
    }
}

function tailLogsFromPanel() {
    const stem = state._selectedContainerStem;
    const serverId = state._selectedContainerServerId;
    const scope = state._selectedContainerScope || 'global';
    if (!stem || !serverId) {
        showLogMessage('Select a container from the sidebar first.');
        return;
    }

    const quadletType = state._selectedContainerType || '';
    const unitName = unitNameFor(quadletType ? stem + '.' + quadletType : stem);
    const tabKey = 'log:' + serverId + ':' + unitName;

    openBottomPanel('logs');

    // Already open → just switch to it, mirroring connectTerminal's dedupe-and-switch.
    if (window._logTabs.has(tabKey)) {
        switchLogTab(tabKey);
        return;
    }

    createLogTab(tabKey, serverId, unitName, scope);
}

function createLogTab(tabKey, serverId, unitName, scope) {
    const cached = Reflect.get(lastStatsPerServer, serverId);
    const serverName = cached?.server_name || ('srv-' + serverId);
    const label = serverName + ':' + unitName.replace(/\.service$/, '');

    // ── Chip ──────────────────────────────────────
    const tabEl = document.createElement('button');
    tabEl.className = 'log-conn-tab';
    tabEl.dataset.key = tabKey;
    tabEl.setAttribute('title', label);

    const labelSpan = document.createElement('span');
    labelSpan.className = 'log-conn-tab-label';
    labelSpan.textContent = label;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'log-conn-tab-close';
    closeBtn.setAttribute('aria-label', 'Close ' + label);
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        closeLogTab(tabKey);
    });

    tabEl.appendChild(labelSpan);
    tabEl.appendChild(closeBtn);
    tabEl.addEventListener('click', function() { switchLogTab(tabKey); });

    const tabsEl = document.getElementById('terminal-conn-tabs');
    if (tabsEl) {
        tabsEl.appendChild(tabEl);
        tabsEl.classList.add('has-tabs');
    }

    // ── Log pane ──────────────────────────────────
    const paneEl = document.createElement('div');
    paneEl.className = 'log-tab-pane hidden';
    paneEl.dataset.key = tabKey;

    const logDiv = document.createElement('div');
    logDiv.className = 'log-stream';
    logDiv.textContent = 'Connecting to log stream...\n';
    paneEl.appendChild(logDiv);

    const bodyEl = document.getElementById('log-tabs-body');
    if (bodyEl) bodyEl.appendChild(paneEl);

    const hint = document.getElementById('log-empty-hint');
    if (hint) hint.style.display = 'none';

    const sinceSelect = document.getElementById('log-since-select');
    const since = sinceSelect ? sinceSelect.value : '15m';

    window._logTabs.set(tabKey, { logDiv: logDiv, tabEl: tabEl, paneEl: paneEl, serverId: serverId, unitName: unitName, scope: scope, since: since });
    switchLogTab(tabKey);

    // ── WebSocket ───────────────────────────────────────
    openLogSocket(tabKey);
}

function openLogSocket(tabKey) {
    const entry = window._logTabs.get(tabKey);
    if (!entry) return;

    const serverId = entry.serverId;
    const unitName = entry.unitName;
    const scope = entry.scope;
    const logDiv = entry.logDiv;
    const tabEl = entry.tabEl;

    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const baseUrl = `${scheme}//${window.location.host}/ws/logs/${encodeURIComponent(serverId)}/${encodeURIComponent(unitName)}`;
    const wsUrl = new URL(baseUrl);
    wsUrl.searchParams.set('scope', scope);
    if (entry.since && entry.since !== 'All') {
        wsUrl.searchParams.set('since', entry.since);
    }
    const ws = new WebSocket(wsUrl.toString());

    ws.onmessage = function(event) {
        logDiv.appendChild(document.createTextNode(event.data));
        logDiv.scrollTop = logDiv.scrollHeight;
    };

    ws.onclose = function() {
        if (entry.ws !== ws) return;
        logDiv.appendChild(document.createTextNode('\n--- Log stream disconnected ---\n'));
        tabEl.classList.add('is-disconnected');
    };

    ws.onerror = function(err) {
        console.error('WebSocket Error:', err);
        logDiv.appendChild(document.createTextNode('\n--- Error connecting to log stream ---\n'));
    };

    entry.ws = ws;
    window._logTabs.set(tabKey, entry);
}

function switchLogTab(key) {
    state._activeLogTabKey = key;

    document.querySelectorAll('.terminal-conn-tab, .log-conn-tab').forEach(function(el) {
        el.classList.remove('is-active');
    });
    document.querySelectorAll('.log-conn-tab').forEach(function(el) {
        el.classList.toggle('is-active', el.dataset.key === key);
    });
    document.querySelectorAll('.log-tab-pane').forEach(function(el) {
        el.classList.toggle('hidden', el.dataset.key !== key);
    });

    const sinceSelect = document.getElementById('log-since-select');
    if (sinceSelect) {
        const entry = window._logTabs.get(key);
        sinceSelect.value = entry?.since || '15m';
    }

    switchBottomTab('logs');
}

function handleClosedLogTabFallback(key) {
    if (window._logTabs.size === 0) {
        const hint = document.getElementById('log-empty-hint');
        if (hint) hint.style.display = '';
        state._activeLogTabKey = null;
    } else if (state._activeLogTabKey === key) {
        switchLogTab(window._logTabs.keys().next().value);
    }
    refreshSessionsStripVisibility();
}

function closeLogTab(key) {
    const session = window._logTabs.get(key);
    if (!session) return;

    if (session.ws && session.ws.readyState !== WebSocket.CLOSED) {
        session.ws.send('STOP');
        session.ws.close();
    }
    session.tabEl?.remove();
    session.paneEl?.remove();

    window._logTabs.delete(key);
    handleClosedLogTabFallback(key);
}

// ── Session Save / Reload / Reconnect ────────────────────
function saveActiveSessionsToStorage() {
    const sessions = { terminals: [], logTails: [] };
    window._terminalTabs.forEach(function(session, tabKey) {
        if (session.serverId && session.containerName) {
            sessions.terminals.push({
                tabKey: tabKey,
                serverId: session.serverId,
                containerName: session.containerName,
                scope: session.scope || 'user',
                cmd: session.cmd || 'bash'
            });
        }
    });
    window._logTabs.forEach(function(session, tabKey) {
        sessions.logTails.push({
            tabKey: tabKey,
            serverId: session.serverId,
            unitName: session.unitName,
            scope: session.scope || 'global'
        });
    });
    if (sessions.terminals.length > 0 || sessions.logTails.length > 0) {
        try {
            localStorage.setItem('qm-pending-reconnect', JSON.stringify(sessions));
        } catch {
            // Ignore localStorage restrictions
        }
    } else {
        try {
            localStorage.removeItem('qm-pending-reconnect');
        } catch {
            // Ignore localStorage restrictions
        }
    }
}

function _beforeunloadHandler(e) {
    if (window._terminalTabs.size > 0 || window._logTabs.size > 0 || window._editorDirty) {
        e.preventDefault();
        e.returnValue = '';
    }
}
window.addEventListener('beforeunload', _beforeunloadHandler);

// Guard htmx swaps of the editor pane when there are unsaved changes.
document.body.addEventListener('htmx:confirm', function(evt) {
    const target = evt.detail?.target;
    if (target?.id !== 'editor-pane' || !window._editorDirty) {
        return;
    }
    evt.preventDefault();
    if (confirm('You have unsaved changes in the editor. Discard them?')) {
        evt.detail.issueRequest();
    }
});

// The server sets HX-Trigger: quadlet-saved on a successful /api/save response.
document.body.addEventListener('quadlet-saved', function() {
    window._editorDirty = false;
    const indicator = document.getElementById('unsaved-indicator');
    if (indicator) indicator.setAttribute('hidden', '');
});

function safeReload() {
    saveActiveSessionsToStorage();
    window.removeEventListener('beforeunload', _beforeunloadHandler);
    window.location.reload();
}

function softRefresh() {
    htmx.trigger(document.body, 'reload-servers');
}

// Report a failed validation request in the results pane and throw. Split out
// of validateQuadlet so that function stays under the cognitive-complexity limit.
async function throwValidationRequestError(response) {
    let message = 'Validation request failed with status ' + response.status;
    try {
        const errorBody = await response.json();
        if (errorBody && typeof errorBody.error === 'string' && errorBody.error) {
            message = errorBody.error;
        }
    } catch (e) {
        // response body was not JSON; fall back to the default message
    }
    const resultsEl = document.getElementById('validation-results');
    if (resultsEl) {
        resultsEl.innerHTML = '';
        resultsEl.removeAttribute('hidden');
        const line = document.createElement('div');
        line.className = 'validation-issue validation-issue-error';
        line.textContent = message;
        resultsEl.appendChild(line);
    }
    throw new Error(message);
}

// ── Editor Validation / Save ────────────────────────────────
async function validateQuadlet() {
    const form = document.getElementById('save-form');
    const serverId = form.querySelector('[name="server_id"]').value;
    const filePath = form.querySelector('[name="file_path"]').value;
    const scope = form.querySelector('[name="scope"]').value;
    const content = window.editor.getValue();

    const body = new FormData();
    body.append('file_path', filePath);
    body.append('scope', scope);
    body.append('content', content);

    const response = await fetch('/api/validate/' + encodeURIComponent(serverId), {
        method: 'POST',
        body: body
    });
    if (!response.ok) {
        await throwValidationRequestError(response);
    }
    const verdict = await response.json();
    const issues = verdict.issues || [];
    const lines = content.split('\n');

    const markers = [];
    issues.forEach(function(issue) {
        if (!issue.key) return;
        for (let i = 0; i < lines.length; i++) {
            const trimmed = lines[i].replace(/^\s+/, '');
            const rest = trimmed.slice(issue.key.length).replace(/^\s+/, '');
            if (trimmed.indexOf(issue.key) === 0 && rest.charAt(0) === '=') {
                markers.push({
                    severity: issue.level === 'error' ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
                    message: issue.message,
                    startLineNumber: i + 1,
                    startColumn: 1,
                    endLineNumber: i + 1,
                    endColumn: lines[i].length + 1
                });
                break;
            }
        }
    });
    monaco.editor.setModelMarkers(window.editor.getModel(), 'quadlet', markers);

    const resultsEl = document.getElementById('validation-results');
    if (resultsEl) {
        resultsEl.innerHTML = '';
        if (verdict.valid && issues.length === 0) {
            resultsEl.setAttribute('hidden', '');
        } else {
            resultsEl.removeAttribute('hidden');
            issues.forEach(function(issue) {
                const line = document.createElement('div');
                line.className = 'validation-issue validation-issue-' + issue.level;
                line.textContent = issue.level + ': ' + issue.message;
                resultsEl.appendChild(line);
            });
            if (verdict.local_only) {
                const note = document.createElement('div');
                note.className = 'validation-note';
                note.textContent = 'local validation only';
                resultsEl.appendChild(note);
            }
        }
    }

    return verdict;
}

async function saveQuadlet() {
    try {
        const verdict = await validateQuadlet();
        if (!verdict.valid && !confirm('Validation found errors. Save anyway?')) {
            return;
        }
    } catch {
        // validation unavailable — do not block saving
    }

    document.getElementById('hidden-content').value = window.editor.getValue();
    document.getElementById('save-form').dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}));
}

// ── Modal Dismissal Handlers ───────────────────────────────
// Wire ESC-key and backdrop-click dismissal onto an already-resolved element.
// Both entry points below (the by-id window helper and the htmx auto-setup)
// share this so the two handler pairs cannot drift apart.
function bindModalDismissal(modal) {
  // Close on ESC key
  const escHandler = function(e) {
    if (e.key === 'Escape' || e.key === 'Esc') {
      modal.remove();
      document.removeEventListener('keydown', escHandler);
    }
  };
  document.addEventListener('keydown', escHandler);

  // Close on backdrop click (outside modal-content)
  modal.addEventListener('click', function(e) {
    if (e.target === modal) {
      modal.remove();
      document.removeEventListener('keydown', escHandler);
    }
  });
}

function setupModalDismissal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  bindModalDismissal(modal);
}

// Auto-setup for modals added via HTMX
document.body.addEventListener('htmx:afterSwap', function() {
  const modals = document.querySelectorAll('.modal-overlay:not([data-dismissal-setup])');
  modals.forEach(function(modal) {
    modal.dataset.dismissalSetup = 'true';
    bindModalDismissal(modal);
  });
});

// ── Window Bridge ──────────────────────────────────────────
// Expose functions and state on `window` for backward compatibility with 45
// inline event handlers across templates/ that still depend on global names.
// This bridge shrinks over time as handlers are converted to delegated listeners.
Object.assign(window, {
  _editorDirty: false,
  _logTabs,
  _terminalTabs,
  applyEditorTheme,
  applyThemePreview,
  applyStatusDots,
  clearThemePreview,
  closeLogTab,
  closeTerminalTab,
  confirmDeleteFile,
  executeDeleteFile,
  handleQuadletsChanged,
  handleStatsError,
  handleStatsUpdate,
  lastStatsPerServer,
  openBottomPanel,
  renderContainerStatsTable,
  runningContainersBySid,
  safeReload,
  selectContainerStem,
  setActiveServer,
  setSelectedQuadletBtn,
  setupModalDismissal,
  showFileContextMenu,
  stemFromUnitName,
  switchLogTab,
  switchTerminalTab,
  toggleChartSelection,
  toggleDensity,
  toggleEditorTheme,
  toggleServerCollapse,
  unitNameFor,
  updateInspectorActivityLog,
  updateInspectorStatsCard,
});

// Scalars live on `state`. Expose them as accessors rather than copying
// them onto window, so the two can never hold divergent values.
Object.defineProperties(window, Object.fromEntries(
    Object.keys(state).map(function (key) {
        return [key, {
            get: function () { return state[key]; },
            set: function (value) { state[key] = value; },
            configurable: true,
            enumerable: true,
        }];
    })
));
