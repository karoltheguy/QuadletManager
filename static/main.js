/* global htmx */
import { lastStatsPerServer, runningContainersBySid, manualStops,
         pendingStarts, _terminalTabs, _logTabs, state } from '@qm/state';
import { el, sendNotification } from '@qm/dom';
import { toggleTheme, toggleDensity, initDensityRadio, toggleEditorTheme,
         initEditorThemeRadio, applyThemePreview, clearThemePreview,
         setEditorMode, applyChartTheme,
         applyEditorTheme } from '@qm/theme';
import { showToast } from '@qm/toast';
import { initModalDismissal, dismissModal } from '@qm/modals';
import { toggleServerEdit, initServerReorder } from '@qm/settings';
import { openBottomPanel, toggleBottomPanel, toggleBottomPanelExpand,
         switchBottomTab, initResizableHandles, initPanel } from '@qm/panel';
import { unitNameFor, stemFromUnitName } from '@qm/units';
import { tailLogsFromPanel, createLogTab, switchLogTab,
         closeLogTab, initLogs } from '@qm/logs';
import { connectTerminal, createTerminalTab, loadFitAddon,
         switchTerminalTab, closeTerminalTab, sessionAddNew,
         initTerminal } from '@qm/terminal';
import { toggleChartSelection, loadMonitorCharts,
         initCpuChart, initMemChart } from '@qm/charts';
import { validateQuadlet, saveQuadlet, initEditor } from '@qm/editor';
import { renderContainerStatsTable } from '@qm/stats';
import { selectMonitoringServer, applyContainerFilter,
         restoreMonitoringServerSelection,
         handleMonitorTabActivation } from '@qm/monitor';
import { updateInspectorStatsCard, updateInspectorActivityLog,
         syncInspectorToggleBtn, toggleInspectorExpand } from '@qm/inspector';
import { toggleServerCollapse, restoreServerCollapseStates,
         setSelectedQuadletBtn, reapplyQuadletSelection,
         restoreQuadletSelection, selectContainerStem, setActiveServer,
         applyStatusDots, showFileContextMenu, confirmDeleteFile,
         executeDeleteFile, initTree } from '@qm/tree';
import { connectSSE, fetchPollHealthSnapshot, applyPollHealthBadges,
         handleQuadletsChanged, handleStatsUpdate, handleStatsError,
         startStatsWaitTimeout } from '@qm/sse';

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


// The tree's context menu asks for the Containers tab through this event
// rather than importing switchTab, which would make tree.js import main.js.
document.body.addEventListener('qm:switch-tab', function (e) {
    switchTab(e.detail.tabId);
});

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

    showToast(message, 'danger');
});

document.body.addEventListener('user-updated', function(evt) {
    const message = evt.detail?.message || 'User updated';
    showToast(message, 'success');
});


// ── Initialize on DOM Ready ──────────────────────────────
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
  'apply-theme-preview': function(btn) {
    applyThemePreview(btn.closest('form'));
  },
  'clear-theme-preview': function() {
    clearThemePreview();
  },
  'set-editor-mode': function(btn) {
    setEditorMode(btn.closest('.color-editor'), btn.dataset.mode);
  },
  'toggle-server-collapse': function(btn) {
    toggleServerCollapse(btn.dataset.serverId);
  },
  'select-quadlet': function(btn) {
    setSelectedQuadletBtn(btn);
    setActiveServer(btn.dataset.serverId);
    selectContainerStem(btn.dataset.stem, btn.dataset.serverId,
                        btn.dataset.scope, btn.dataset.type);
  },
  'toggle-server-edit': function(btn) {
    toggleServerEdit(btn.dataset.serverId);
  },
  'dismiss-modal': function(btn) {
    dismissModal(btn);
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
  'toggle-density': function(elt) {
    toggleDensity(elt.value);
  },
  'toggle-editor-theme': function(elt) {
    toggleEditorTheme(elt.value);
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

// Right-click actions read `data-context-action` rather than `data-action`,
// because the quadlet tree button carries both and one attribute cannot hold
// two. The dispatch passes the event through: showFileContextMenu needs it for
// preventDefault() and the pointer coordinates.
const delegatedContextMenuActions = {
  'show-file-context-menu': function(elt, e) {
    showFileContextMenu(e, elt.dataset.serverId, elt.dataset.path, elt.dataset.scope);
  },
};

document.addEventListener('contextmenu', function(e) {
  const elt = e.target.closest('[data-context-action]');
  if (!elt) return;
  const action = elt.dataset.contextAction;
  if (!Object.hasOwn(delegatedContextMenuActions, action)) return;
  Reflect.get(delegatedContextMenuActions, action)(elt, e);
});

// Clear theme preview after color editor form submissions. Replaces hx-on::after-request
// attributes because htmx hx-on bodies are evaluated against globals (depending on the
// window bridge just like inline handlers) while the inline-handler test cannot see them.
document.addEventListener('htmx:afterRequest', function (e) {
  if (e.target.closest?.('.color-editor-form')) {
    clearThemePreview();
  }
});

initPanel();


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
initTerminal();
initLogs();
initTree();
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

startStatsWaitTimeout();
    document.documentElement.dataset.appReady = '1';
});


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

function safeReload() {
    saveActiveSessionsToStorage();
    window.removeEventListener('beforeunload', _beforeunloadHandler);
    window.location.reload();
}

function softRefresh() {
    htmx.trigger(document.body, 'reload-servers');
}

initModalDismissal();
initServerReorder();
initEditor();

// ── Window Bridge ──────────────────────────────────────────
// Expose functions and state on `window` for the three consumers still reading
// global names: the few remaining inline handlers in templates/, main.js's own
// window reads, and tests/e2e/ via page.evaluate. selectContainerStem and
// setActiveServer are held here only by that last one, test_inspector_stats_card.py
// and test_monitoring_ui.py, and no longer by any inline handler.
Object.assign(window, {
  _editorDirty: false,
  _logTabs,
  _terminalTabs,
  applyEditorTheme,
  applyStatusDots,
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
  stemFromUnitName,
  switchLogTab,
  switchTerminalTab,
  toggleChartSelection,
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
