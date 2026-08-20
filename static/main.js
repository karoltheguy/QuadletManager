/* global htmx, Chart, Terminal, closeLogTab, closeTerminalTab, connectTerminal, healthHistoryChart, loadMonitorCharts, monitoringChart, openBottomPanel, selectMonitoringServer, switchBottomTab, switchLogTab, switchTerminalTab, tailLogsFromPanel, require */
// ── Server Collapse ───────────────────────────────────────
window.toggleServerCollapse = function(serverId) {
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
};

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
function toggleProfileMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById('profile-menu');
    menu.hidden = !menu.hidden;
}
window.toggleProfileMenu = toggleProfileMenu;

document.addEventListener('click', function() {
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
window.toggleTheme = toggleTheme;

// ── Density Toggle ───────────────────────────────────────
window.toggleDensity = function(value) {
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
};

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
window.toggleEditorTheme = function(value) {
    try {
        localStorage.setItem('qm-editor-theme', value);
    } catch {
        // Ignore localStorage restrictions
    }
    applyEditorTheme();
};

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

// WCAG contrast helpers (mirrors api/routes.py's _linearize / _relative_luminance /
// _contrast_ratio / _on_primary_for, see lines ~1285-1322). These must stay in
// exact result-parity with the Python implementation -- see
// tests/test_theme_preview_on_primary.py's parity assertion over a shared color
// corpus.
function linearize(channel) {
    if (channel <= 0.04045) return channel / 12.92;
    return Math.pow((channel + 0.055) / 1.055, 2.4);
}

function relativeLuminance(hexColor) {
    const hex = hexColor.replace(/^#/, '');
    let r = Number.parseInt(hex.substring(0, 2), 16) / 255;
    let g = Number.parseInt(hex.substring(2, 4), 16) / 255;
    let b = Number.parseInt(hex.substring(4, 6), 16) / 255;
    r = linearize(r);
    g = linearize(g);
    b = linearize(b);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(hexA, hexB) {
    const la = relativeLuminance(hexA);
    const lb = relativeLuminance(hexB);
    const lighter = Math.max(la, lb);
    const darker = Math.min(la, lb);
    return (lighter + 0.05) / (darker + 0.05);
}

const ON_PRIMARY_CANDIDATES = ['#1c1f24', '#ffffff', '#000000'];
const WCAG_AA_MIN = 4.5;

function onPrimaryFor(brandHex) {
    for (const candidate of ON_PRIMARY_CANDIDATES) {
        if (contrastRatio(candidate, brandHex) >= WCAG_AA_MIN) return candidate;
    }
    return '#ffffff';
}

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
window.applyThemePreview = applyThemePreview;

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
window.unitNameFor = unitNameFor;

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
window.stemFromUnitName = stemFromUnitName;

// Mark the clicked quadlet tree button as selected (inset state).
// Called inline from partials/quadlet_tree.html onclick.
function setSelectedQuadletBtn(el) {
    document.querySelectorAll('.quadlet-tree-btn.is-selected')
        .forEach(function (b) { b.classList.remove('is-selected'); });
    if (el) el.classList.add('is-selected');
}
window.setSelectedQuadletBtn = setSelectedQuadletBtn;

// Re-apply the .is-selected class after htmx swaps the quadlet tree.
// Source of truth is window._selectedContainerStem / _selectedContainerServerId,
// set by selectContainerStem() — the editor pane is the real state, we're
// just re-syncing the sidebar visual to match.
function reapplyQuadletSelection() {
    const stem = window._selectedContainerStem;
    const sid  = window._selectedContainerServerId;
    if (!stem || !sid) return;
    const btn = document.querySelector(
        '.quadlet-tree-btn[data-stem="' + stem + '"][data-server-id="' + sid + '"]'
    );
    if (btn) btn.classList.add('is-selected');
}
// Restore the saved quadlet selection after the tree loads via HTMX.
// Uses a once-flag so subsequent tree re-renders don't clobber user clicks.
function restoreQuadletSelection() {
    if (window._quadletRestored) return;
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
    window._quadletRestored = true;
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

const manualStops = new Set(); // tracks serverId:stem that we intentionally stopped
const pendingStarts = {}; // tracks stems waiting for active status

function el(tag, attrs, children) {
    const element = document.createElement(tag);
    if (attrs) {
        Object.keys(attrs).forEach(function(k) {
            const val = Reflect.get(attrs, k);
            if (k === 'className') {
                element.className = val;
            } else if (k === 'style' && typeof val === 'object') {
                Object.keys(val).forEach(function(sk) {
                    Reflect.set(element.style, sk, Reflect.get(val, sk));
                });
            } else {
                element.setAttribute(k, val);
            }
        });
    }
    if (children !== undefined && children !== null) {
        if (Array.isArray(children)) {
            children.forEach(function(child) {
                if (typeof child === 'string') {
                    element.appendChild(document.createTextNode(child));
                } else if (child) {
                    element.appendChild(child);
                }
            });
        } else if (typeof children === 'string') {
            element.textContent = children;
        } else {
            element.appendChild(children);
        }
    }
    return element;
}

function sendNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body: body });
    }
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
let statsChart = null;
let cpuHistoryChart = null;
let memHistoryChart = null;

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

function hexToRgba(hex, alpha) {
    const r = Number.parseInt(hex.slice(1, 3), 16);
    const g = Number.parseInt(hex.slice(3, 5), 16);
    const b = Number.parseInt(hex.slice(5, 7), 16);
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
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
    const charts = [statsChart];
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
    [cpuHistoryChart, memHistoryChart].forEach(function(chart) {
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
window.applyEditorTheme = applyEditorTheme;

// Track which server the user is currently working in.
// The stats chart only renders updates for this server.
// null = show whichever server reports first (auto-set on first update).
window.activeServerId = null;

// Cache the last-seen data per server so we can re-render immediately
// when the user switches servers without waiting for the next 5s poll.
const lastStatsPerServer = {};

// Per-server map of currently running container name stems.
// Key: serverId (int), Value: Set<string> of lowercase container name stems.
// Explicitly attached to window so page.evaluate() in tests can access it.
const runningContainersBySid = window.runningContainersBySid = {};

// Active container name filter for the Monitor view (lowercase substring).
// Empty string means show all containers.
let monitorContainerFilter = '';

// Last unhealthy count announced to #monitor-health-status, so repeated
// SSE ticks with an unchanged count do not re-trigger the live region.
let lastAnnouncedUnhealthy = null;

// Currently selected container stem in the inspector (lowercase).
window._selectedContainerStem = null;
window._selectedContainerServerId = null;
window._selectedContainerScope = null;
window._selectedContainerType = null;
// Set to true after the saved quadlet selection has been restored once,
// so subsequent htmx:afterSwap tree re-renders don't override user clicks.
window._quadletRestored = false;

window.selectContainerStem = function(stem, serverId, scope, type) {
    window._selectedContainerStem = (stem || '').toLowerCase();
    window._selectedContainerServerId = Number.parseInt(serverId, 10);
    window._selectedContainerScope = scope || 'global';
    window._selectedContainerType = (type || '').toLowerCase();
    try {
        localStorage.setItem('qm-selected-quadlet', JSON.stringify({
            stem: window._selectedContainerStem,
            serverId: window._selectedContainerServerId,
            scope: window._selectedContainerScope
        }));
    } catch {
        // Ignore localStorage restrictions
    }
    const emptyEl = document.getElementById('inspector-empty-state');
    if (emptyEl) emptyEl.style.display = stem ? 'none' : '';
    updateInspectorStatsCard();
    updateInspectorActivityLog();
};

function updateInspectorStatsCard() {
    const card = document.getElementById('container-stats-card');
    if (!card) return;

    const stem = window._selectedContainerStem;
    const serverId = window._selectedContainerServerId;
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

    const stem = window._selectedContainerStem;
    const serverId = window._selectedContainerServerId;
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

function getRelativeTime(timestamp) {
    const now = Math.floor(Date.now() / 1000);
    const diff = now - timestamp;

    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}


// Called from quadlet_tree.html when the user clicks a file button.
window.setActiveServer = function(serverId) {
    serverId = Number.parseInt(serverId, 10);
    if (window.activeServerId === serverId) return;
    window.activeServerId = serverId;
    // Re-render immediately with cached data for this server, if we have it.
    const cached = Reflect.get(lastStatsPerServer, serverId);
    if (cached) {
        updateStats(cached);
        applyStatusDots(serverId);
    } else {
        // No data yet for this server – show a waiting message.
        const tableEl = document.getElementById('stats-table');
        if (tableEl) {
            tableEl.textContent = '';
            tableEl.appendChild(el('div', { className: 'p-4 text-muted italic' }, 'Waiting for stats data...'));
        }
        if (statsChart) {
            statsChart.data.labels = [];
            statsChart.data.datasets[0].data = [];
            statsChart.data.datasets[1].data = [];
            statsChart.update();
        }
    }
};

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


function buildBarChartConfig() {
  const t = getChartTheme();
  return {
    type: 'bar',
    data: {
      labels: [],
      datasets: [
        {
          label: 'CPU %',
          data: [],
          backgroundColor: t.accentBg,
          borderColor: t.accent,
          borderWidth: 1,
          borderRadius: 4
        },
        {
          label: 'Memory %',
          data: [],
          backgroundColor: t.secondaryBg,
          borderColor: t.secondary,
          borderWidth: 1,
          borderRadius: 4
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        y: {
          beginAtZero: true,
          max: 100,
          ticks: {
            color: t.tickColor,
            font: { size: 11 },
            callback: function(value) { return value + '%'; }
          },
          grid: { color: t.gridColor }
        },
        x: {
          ticks: {
            color: t.tickColor,
            font: { size: 11 },
            maxRotation: 45,
            minRotation: 0
          },
          grid: { display: false }
        }
      },
      plugins: {
        legend: {
          labels: {
            color: t.legendColor,
            font: { size: 11 },
            boxWidth: 12,
            padding: 8
          }
        },
        tooltip: {
          backgroundColor: t.tooltipBg,
          titleColor: t.tooltipTitle,
          bodyColor: t.tooltipBody,
          borderColor: t.tooltipBorder,
          borderWidth: 1,
          cornerRadius: 6,
          padding: 8
        }
      }
    }
  };
}

function initStatsChart() {
  const ctx = document.getElementById('stats-chart');
  if (!ctx) return;
  statsChart = new Chart(ctx, buildBarChartConfig());
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
        legend: {
          labels: { color: t.legendColor, font: { size: 11 }, boxWidth: 12, padding: 8 }
        },
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
  cpuHistoryChart = new Chart(ctx, _buildTimeSeriesConfig());
}

function initMemChart() {
  const ctx = document.getElementById('mem-history-chart');
  if (!ctx) return;
  memHistoryChart = new Chart(ctx, _buildTimeSeriesConfig());
}

window._monitorChartMinutes = 60;

window.loadMonitorCharts = function(minutes, btnEl) {
  window._monitorChartMinutes = minutes;

  if (btnEl) {
    document.querySelectorAll('.health-range-btn').forEach(function(b) { b.classList.remove('active'); });
    btnEl.classList.add('active');
  }

  const serverId = window.activeServerId;
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

      if (!cpuHistoryChart || !memHistoryChart) return;

      // Build unified sorted timestamp labels from all containers
      const tsSet = new Set();
      data.forEach(function(c) { c.history.forEach(function(p) { tsSet.add(p.ts); }); });
      const tsSorted = Array.from(tsSet).sort(function(a, b) { return a - b; });

      const _rangeMinutes = window._monitorChartMinutes;
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
      const filteredData = monitorContainerFilter
        ? data.filter(function(c) { return (c.container_name || '').toLowerCase().includes(monitorContainerFilter); })
        : data;

      const cpuDatasets = filteredData.map(function(c, i) {
        const byTs = {};
        c.history.forEach(function(p) { Reflect.set(byTs, p.ts, p.cpu !== null ? p.cpu : null); });
        const color = HISTORY_COLORS[i % HISTORY_COLORS.length];
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

      const memDatasets = filteredData.map(function(c, i) {
        const byTs = {};
        c.history.forEach(function(p) { Reflect.set(byTs, p.ts, p.mem !== null ? p.mem : null); });
        const color = HISTORY_COLORS[i % HISTORY_COLORS.length];
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

      cpuHistoryChart.data.labels = labels;
      cpuHistoryChart.data.datasets = cpuDatasets;
      cpuHistoryChart.update();

      memHistoryChart.data.labels = labels;
      memHistoryChart.data.datasets = memDatasets;
      memHistoryChart.update();
    })
    .catch(function(err) {
      console.error('Monitor chart fetch error:', err);
      const errorEl = document.getElementById('monitor-charts-error');
      if (errorEl) errorEl.style.display = '';
    });
};

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
        if (u && u.unit) index.set(u.unit, u);
    });
    return index;
}

function getUnitBadgeInfo(activeState) {
    const s = activeState || '';
    if (s === 'failed') return { badgeClass: 'unit-failed', label: s };
    if (s === 'active') return { badgeClass: 'unit-active', label: s };
    return { badgeClass: 'unit-other', label: s || STAT_PLACEHOLDER };
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

function renderContainerRow(c, unitIndex) {
    const cpuClass = getPercentClass(parsePercent(c.cpu));
    const memClass = getPercentClass(parsePercent(c.mem));
    const badgeInfo = getHealthBadgeInfo(c.health);

    const tr = document.createElement('tr');
    tr.className = 'border-b';

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
    const unitRec = unitIndex && c.unit ? unitIndex.get(c.unit) : null;
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
        th.textContent = h.text;
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

function updateStats(data) {
    const containers = data.containers || [];

    // ── Update Chart ──
    if (statsChart) {
        statsChart.data.labels = containers.map(function(c) { return c.name; });
        statsChart.data.datasets[0].data = containers.map(function(c) { return parsePercent(c.cpu); });
        statsChart.data.datasets[1].data = containers.map(function(c) { return parsePercent(c.mem); });
        statsChart.update();
    }

    renderContainerStatsTable('stats-table', data);
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

function handleStatsUpdate(e) {
  try {
    const data = JSON.parse(e.data);
    _statsReceived = true;
    if (_statsWaitTimeout) { clearTimeout(_statsWaitTimeout); _statsWaitTimeout = null; }

    const sets = cacheServerStats(data);

    detectUnexpectedlyStopped(data.server_id, sets.oldSet, sets.runningSet);

    applyStatusDots(data.server_id);

    if (data.server_id === window._selectedContainerServerId) {
      updateInspectorStatsCard();
    }

    if (window.activeServerId === null) {
      window.activeServerId = data.server_id;
    }

    populateServerSelector();

    if (data.server_id !== window.activeServerId) return;

    const tableEl = document.getElementById('stats-table');
    if (tableEl) tableEl.classList.remove('stats-error');
    updateStats(data);
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
  indicator.textContent = 'Sync cycle: ' + Number(cycle.duration).toFixed(1) + 's / ' + cycle.interval + 's';
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

window.handleQuadletsChanged = function (data) {
  const container = document.querySelector(
    '.server-quadlet-tree[data-server-id="' + data.server_id + '"]'
  );
  if (!container) return;
  htmx.ajax('GET', '/api/quadlets/' + data.server_id,
            { target: container, swap: 'innerHTML' });
};

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
  evtSource.addEventListener('stats_error', function(e) {
    try {
      const data = JSON.parse(e.data);
      const tableEl = document.getElementById('stats-table');
      if (tableEl) {
        tableEl.classList.add('stats-error');
        tableEl.textContent = '';
        tableEl.appendChild(createStatsErrorDOM(data.server_name, data.error));
      }
      // Also show error in monitoring table
      const monitoringTableEl = document.getElementById('monitoring-stats-table');
      if (monitoringTableEl) {
        monitoringTableEl.textContent = '';
        monitoringTableEl.appendChild(createStatsErrorDOM(data.server_name, data.error));
      }
    } catch (err) {
      console.error('Stats error parse error:', err);
    }
  });

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
  if (cpuHistoryChart) cpuHistoryChart.resize();
  if (memHistoryChart) memHistoryChart.resize();
  loadMonitorCharts(window._monitorChartMinutes || 15);
}

function updateNavItemActive(tabId) {
  document.querySelectorAll('.nav-item').forEach(function(btn) {
    if (btn.innerText.toLowerCase() === tabId) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
}

window.switchTab = function(tabId) {
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
};

// ── SSH Key Dropdown Refresh ──────────────────────────────
// The hx-trigger="load" on the select fires once at DOMContentLoaded when the
// settings pane is display:none, making HTMX event-timing unreliable. Refresh
// explicitly whenever the dropdown becomes visible instead (issue #86).
function refreshSshKeyDropdown() {
  const sel = document.querySelector('select[name="ssh_key_id"]');
  if (sel) htmx.ajax('GET', '/api/keys/options', {target: sel, swap: 'innerHTML'});
}

// ── Settings Section Switcher ─────────────────────────────
window.showSettingsSection = function(name) {
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
};

// ── Inspector Expand / Collapse Toggle ───────────────────
function syncInspectorToggleBtn() {
  const btn = document.getElementById('inspector-expand-btn');
  if (!btn) return;
  const expanded = document.body.classList.contains('inspector-expanded');
  btn.title = expanded ? 'Restore inspector' : 'Collapse inspector';
  btn.setAttribute('aria-label', btn.title);
}

window.toggleInspectorExpand = function() {
  const expanded = document.body.classList.toggle('inspector-expanded');
  localStorage.setItem('qm-inspector-expanded', expanded ? 'true' : 'false');
  syncInspectorToggleBtn();
  // Monaco must re-layout after the inspector width changes
  if (window.editor) window.editor.layout();
};

// ── Monitoring Server Selector ────────────────────────────
function showMonitoringEmptyState(emptyEl, contentEl) {
  if (emptyEl) emptyEl.style.display = '';
  if (contentEl) contentEl.style.display = 'none';
  const barEl = document.getElementById('monitor-stat-bar');
  if (barEl) barEl.style.display = 'none';
  window._monitoringServerId = null;
}

function renderMonitoringServerStats(numId) {
  const cached = Reflect.get(lastStatsPerServer, numId);
  if (cached) {
    updateMonitoringView(cached);
    loadMonitorCharts(window._monitorChartMinutes || 15);
  } else {
    const tableEl = document.getElementById('monitoring-stats-table');
    if (tableEl) {
      tableEl.textContent = '';
      tableEl.appendChild(el('div', { className: 'p-4 text-muted italic' }, 'Waiting for stats data...'));
    }
    if (monitoringChart) {
      monitoringChart.data.labels = [];
      monitoringChart.data.datasets[0].data = [];
      monitoringChart.data.datasets[1].data = [];
      monitoringChart.update();
    }
  }
}

window.selectMonitoringServer = function(serverId) {
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

  window._monitoringServerId = numId;

  if (window.activeServerId === numId) return;
  window.activeServerId = numId;

  renderMonitoringServerStats(numId);
};

function updateMonitoringView(data) {
  // Only render when this data is for the server currently selected in the dropdown.
  if (data.server_id !== window._monitoringServerId) return;

  // Apply the active filter to every part of the pane: table, charts and the
  // glance bar all narrow together, so the numbers always describe what is
  // on screen.
  const allContainers = data.containers || [];
  const containers = monitorContainerFilter
    ? allContainers.filter(function(c) {
        return (c.name || '').toLowerCase().includes(monitorContainerFilter);
      })
    : allContainers;

  const filteredData = { server_id: data.server_id, server_name: data.server_name, containers: containers, units: data.units };

  // Append the latest SSE data point to the live time-series charts.
  if ((cpuHistoryChart || memHistoryChart) && allContainers.length > 0) {
    const now = new Date();
    const timeLabel = now.getHours().toString().padStart(2, '0') + ':' +
                    now.getMinutes().toString().padStart(2, '0') + ':' +
                    now.getSeconds().toString().padStart(2, '0');
    const windowSec = (window._monitorChartMinutes || 15) * 60;

    const appendToChart = function(chart, valueKey) {
      if (!chart) return;
      const containersToShow = monitorContainerFilter
        ? allContainers.filter(function(c) { return (c.name || '').toLowerCase().includes(monitorContainerFilter); })
        : allContainers;

      // Drop datasets for containers the filter no longer matches; otherwise a
      // series drawn before the filter was typed stays on the canvas with
      // nothing appending to it, since this path never refetches history.
      const visibleNames = {};
      containersToShow.forEach(function(c) { visibleNames[c.name] = true; });
      chart.data.datasets = chart.data.datasets.filter(function(ds) { return visibleNames[ds.label]; });

      // Build a map of current dataset labels for quick lookup
      const datasetByName = {};
      chart.data.datasets.forEach(function(ds) { datasetByName[ds.label] = ds; });

      containersToShow.forEach(function(c) {
        const val = valueKey === 'cpu' ? parsePercent(c.cpu) : parsePercent(c.mem);
        if (datasetByName[c.name]) {
          datasetByName[c.name].data.push(val);
        } else {
          // New container not yet in chart — add a new dataset
          const color = HISTORY_COLORS[chart.data.datasets.length % HISTORY_COLORS.length];
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

      chart.update('none');
    }

    appendToChart(cpuHistoryChart, 'cpu');
    appendToChart(memHistoryChart, 'mem');
  }

  renderContainerStatsTable('monitoring-stats-table', filteredData);
  updateSummaryStrip(filteredData);
  updateFilterCount(containers.length, allContainers.length);
}

// "N of M shown" next to the filter box. Both counts come from the running
// container list, so this reports what the table and charts are showing and
// not the stopped containers the glance bar also counts.
function updateFilterCount(shown, total) {
  const el = document.getElementById('monitor-filter-count');
  if (!el) return;

  if (!monitorContainerFilter) {
    el.hidden = true;
    el.textContent = '';
    return;
  }

  el.textContent = shown + ' of ' + total + ' shown';
  el.hidden = false;
}

function applyContainerFilter(value) {
  monitorContainerFilter = (value || '').toLowerCase().trim();
  const serverId = window._monitoringServerId;
  const cached = Reflect.get(lastStatsPerServer, serverId);
  if (serverId && cached) {
    updateMonitoringView(cached);
  }
}
window.applyContainerFilter = applyContainerFilter;

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
    return !monitorContainerFilter || stem.includes(monitorContainerFilter);
  });
  const total = filteredUnits.length;
  const running = filteredUnits.filter(function(u) { return u.active_state === 'active'; }).length;
  // A failed unit is not simply "stopped": stopped stays total - running so the
  // three load counts still add up, and failed overlaps it as its own signal.
  const failed = filteredUnits.filter(function(u) { return u.active_state === 'failed'; }).length;
  return { total: total, running: running, stopped: total - running, failed: failed };
}

function setStatText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
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

function populateServerSelector() {
  const select = document.getElementById('monitoring-server-select');
  if (!select) return;

  // Clear existing options except the placeholder
  select.textContent = '';
  select.appendChild(el('option', { value: '' }, 'Select a server...'));

  // Add servers from the cached stats data
  Object.keys(lastStatsPerServer).forEach(function(serverId) {
    const data = Reflect.get(lastStatsPerServer, serverId);
    const option = document.createElement('option');
    option.value = serverId;
    option.textContent = data.server_name || ('Server ' + serverId);
    if (window._monitoringServerId && Number.parseInt(serverId, 10) === window._monitoringServerId) {
      option.selected = true;
    }
    select.appendChild(option);
  });

  // Restore saved monitor server on first population if not yet selected.
  if (!window._monitoringServerId) {
    let savedServer;
    try {
      savedServer = localStorage.getItem('qm-monitor-server');
    } catch {
      // Ignore localStorage restrictions
    }
    const cachedSaved = Reflect.get(lastStatsPerServer, savedServer);
    if (savedServer && cachedSaved) {
      select.value = savedServer;
      selectMonitoringServer(savedServer);
    }
  }
}

// ── Terminal Session Management ──────────────────────────
window._terminalTabs = new Map();   // tabKey → { term, ws, fitAddon, tabEl, paneEl }
window._activeTerminalTabKey = null;
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
window.openBottomPanel = function(tab) {
    const panel = document.getElementById('bottom-panel');
    if (!panel) return;
    panel.classList.remove('is-collapsed');
    const body = panel.querySelector('.bottom-panel-body');
    const handle = document.getElementById('bottom-panel-resize-handle');
    if (body) body.classList.remove('hidden');
    if (handle) handle.classList.remove('hidden');
    localStorage.setItem('qm-bottom-panel-open', '1');
    if (tab) switchBottomTab(tab);
    const key = window._activeTerminalTabKey;
    if (key) {
        const session = window._terminalTabs.get(key);
        if (session?.fitAddon) session.fitAddon.fit();
    }
};

function fitActiveTerminal() {
    const key = window._activeTerminalTabKey;
    if (!key) return;
    const session = window._terminalTabs.get(key);
    if (session?.fitAddon) {
        session.fitAddon.fit();
    }
}

window.toggleBottomPanel = function() {
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
};

window.toggleBottomPanelExpand = function() {
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
    const key = window._activeTerminalTabKey;
    if (key) {
        const session = window._terminalTabs.get(key);
        if (session?.fitAddon) session.fitAddon.fit();
    }
};

window.switchBottomTab = function(pane) {
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
        const key = window._activeTerminalTabKey;
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
        const logKey = window._activeLogTabKey;
        if (logKey) {
            document.querySelectorAll('.log-conn-tab').forEach(function(el) {
                el.classList.toggle('is-active', el.dataset.key === logKey);
            });
        }
    }
};

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

window.connectTerminal = function() {
    const stem = window._selectedContainerStem;
    const serverId = window._selectedContainerServerId;
    const scope = window._selectedContainerScope || 'global';
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
};

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

window.switchTerminalTab = function(key) {
    window._activeTerminalTabKey = key;

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
};

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
        window._activeTerminalTabKey = null;
    } else if (window._activeTerminalTabKey === key) {
        switchTerminalTab(window._terminalTabs.keys().next().value);
    }
    refreshSessionsStripVisibility();
}

window.closeTerminalTab = function(key) {
    const session = window._terminalTabs.get(key);
    if (!session) return;

    disposeTerminalSession(session);
    removeTerminalDOM(session);

    window._terminalTabs.delete(key);
    handleClosedTabFallback(key);
};

window.disconnectTerminal = function() {
    const key = window._activeTerminalTabKey;
    if (key) closeTerminalTab(key);
};

window.sessionAddNew = function() {
    const activeTab = document.querySelector('.bottom-tab.is-active');
    const pane = activeTab ? activeTab.dataset.pane : 'terminal';
    if (pane === 'logs') {
        tailLogsFromPanel();
    } else {
        connectTerminal();
    }
};

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

            const key = window._activeLogTabKey;
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
    const key = window._activeTerminalTabKey;
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
                if (statsChart) statsChart.resize();
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
                if (statsChart) statsChart.resize();
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
                if (statsChart) statsChart.resize();
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
                if (statsChart) statsChart.resize();
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
                const _rk = window._activeTerminalTabKey;
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
                const _uk = window._activeTerminalTabKey;
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

window.switchTab(localStorage.getItem('qm-active-tab') || 'overview');
switchBottomTab(localStorage.getItem('qm-bottom-tab') || 'terminal');
initStatsChart();
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

// If no stats arrive within 15s of page load, update the placeholder
// so the user isn't left staring at "Waiting for stats data..." forever.
_statsWaitTimeout = setTimeout(function() {
  if (!_statsReceived) {
    const tableEl = document.getElementById('stats-table');
    if (tableEl) {
      tableEl.textContent = '';
      tableEl.appendChild(el('div', { className: 'p-4 text-warning italic' }, 'No stats received yet — verify server connectivity.'));
    }
    const monitoringTableEl = document.getElementById('monitoring-stats-table');
    if (monitoringTableEl) {
      monitoringTableEl.textContent = '';
      monitoringTableEl.appendChild(el('div', { className: 'p-4 text-warning italic' }, 'No stats received yet — verify server connectivity.'));
    }
  }
}, 15000);
});

// ── File Deletion ─────────────────────────────────────────
let _ctxMenu = null;

window.showFileContextMenu = function(event, serverId, path, scope) {
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
        window.switchTab('containers');
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
};

window.confirmDeleteFile = function(serverId, path, scope) {
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
};

window.executeDeleteFile = async function(serverId, path, scope) {
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
};

// ── Real-time Logs WebSocket ─────────────────────────────
window._logTabs = new Map();   // tabKey → { ws, logDiv, tabEl, paneEl, serverId, unitName, scope }
window._activeLogTabKey = null;

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

window.tailLogsFromPanel = function() {
    const stem = window._selectedContainerStem;
    const serverId = window._selectedContainerServerId;
    const scope = window._selectedContainerScope || 'global';
    if (!stem || !serverId) {
        showLogMessage('Select a container from the sidebar first.');
        return;
    }

    const quadletType = window._selectedContainerType || '';
    const unitName = unitNameFor(quadletType ? stem + '.' + quadletType : stem);
    const tabKey = 'log:' + serverId + ':' + unitName;

    openBottomPanel('logs');

    // Already open → just switch to it, mirroring connectTerminal's dedupe-and-switch.
    if (window._logTabs.has(tabKey)) {
        switchLogTab(tabKey);
        return;
    }

    createLogTab(tabKey, serverId, unitName, scope);
};

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

window.switchLogTab = function(key) {
    window._activeLogTabKey = key;

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
};

function handleClosedLogTabFallback(key) {
    if (window._logTabs.size === 0) {
        const hint = document.getElementById('log-empty-hint');
        if (hint) hint.style.display = '';
        window._activeLogTabKey = null;
    } else if (window._activeLogTabKey === key) {
        switchLogTab(window._logTabs.keys().next().value);
    }
    refreshSessionsStripVisibility();
}

window.closeLogTab = function(key) {
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
};

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

window.safeReload = function() {
    saveActiveSessionsToStorage();
    window.removeEventListener('beforeunload', _beforeunloadHandler);
    window.location.reload();
};

window.softRefresh = function() {
    htmx.trigger(document.body, 'reload-servers');
    loadMonitorCharts(window._monitorChartMinutes || 15);
};

// ── Editor Validation / Save ────────────────────────────────
window.validateQuadlet = async function() {
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
};

window.saveQuadlet = async function saveQuadlet() {
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
};

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

window.setupModalDismissal = function(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  bindModalDismissal(modal);
};

// Auto-setup for modals added via HTMX
document.body.addEventListener('htmx:afterSwap', function() {
  const modals = document.querySelectorAll('.modal-overlay:not([data-dismissal-setup])');
  modals.forEach(function(modal) {
    modal.dataset.dismissalSetup = 'true';
    bindModalDismissal(modal);
  });
});
