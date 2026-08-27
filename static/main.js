/* global htmx */
import { lastStatsPerServer, runningContainersBySid, manualStops,
         pendingStarts, monitorChartSelection,
         _terminalTabs, _logTabs, state } from '@qm/state';
import { el, sendNotification, getRelativeTime } from '@qm/dom';
import { toggleTheme, toggleDensity, initDensityRadio, toggleEditorTheme,
         initEditorThemeRadio, applyThemePreview, clearThemePreview,
         setEditorMode, applyChartTheme,
         applyEditorTheme } from '@qm/theme';
import { showToast } from '@qm/toast';
import { setupModalDismissal, initModalDismissal } from '@qm/modals';
import { openBottomPanel, toggleBottomPanel, toggleBottomPanelExpand,
         switchBottomTab, initResizableHandles, initPanel } from '@qm/panel';
import { unitNameFor, stemFromUnitName } from '@qm/units';
import { tailLogsFromPanel, createLogTab, switchLogTab,
         closeLogTab, initLogs } from '@qm/logs';
import { connectTerminal, createTerminalTab, loadFitAddon,
         switchTerminalTab, closeTerminalTab, sessionAddNew,
         initTerminal } from '@qm/terminal';
import { chartColorFor, toggleChartSelection,
         applyChartSelection, loadMonitorCharts,
         initCpuChart, initMemChart } from '@qm/charts';
import { validateQuadlet, saveQuadlet, initEditor } from '@qm/editor';
import { parsePercent, mergeUnitRows, renderContainerStatsTable,
         updateSummaryStrip, updateFilterCount } from '@qm/stats';

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





// Track which server the user is currently working in.
// The stats chart only renders updates for this server.
// null = show whichever server reports first (auto-set on first update).

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
  if (e.target.closest && e.target.closest('.color-editor-form')) {
    clearThemePreview();
  }
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
    setupModalDismissal('delete-confirm-modal');
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
