/* global htmx */
import { lastStatsPerServer, runningContainersBySid, manualStops,
         pendingStarts, _terminalTabs, _logTabs, state } from '@qm/state';
import { el, sendNotification } from '@qm/dom';
import { toggleTheme, toggleDensity, initDensityRadio, toggleEditorTheme,
         initEditorThemeRadio, applyThemePreview, clearThemePreview,
         setEditorMode, applyChartTheme,
         applyEditorTheme } from '@qm/theme';
import { showToast } from '@qm/toast';
import { initModalDismissal } from '@qm/modals';
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
import { updateMonitoringView, selectMonitoringServer, applyContainerFilter,
         restoreMonitoringServerSelection,
         handleMonitorTabActivation } from '@qm/monitor';
import { updateInspectorStatsCard, updateInspectorActivityLog,
         syncInspectorToggleBtn, toggleInspectorExpand } from '@qm/inspector';
import { toggleServerCollapse, restoreServerCollapseStates,
         setSelectedQuadletBtn, reapplyQuadletSelection,
         restoreQuadletSelection, selectContainerStem, setActiveServer,
         applyStatusDots, showFileContextMenu, confirmDeleteFile,
         executeDeleteFile, initTree } from '@qm/tree';

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
            showToast('⚠ ' + data.message + ' (' + data.file_path + ')', 'warning');
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
initEditor();

// ── Window Bridge ──────────────────────────────────────────
// Expose functions and state on `window` for backward compatibility with 45
// inline event handlers across templates/ that still depend on global names.
// This bridge shrinks over time as handlers are converted to delegated listeners.
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
  setSelectedQuadletBtn,
  showFileContextMenu,
  stemFromUnitName,
  switchLogTab,
  switchTerminalTab,
  toggleChartSelection,
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
