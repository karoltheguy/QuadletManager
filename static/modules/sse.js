/* global htmx */
/**
 * Server-Sent Events client: stats streaming, poll health, and quadlet changes.
 */

import { state, lastStatsPerServer, runningContainersBySid,
         manualStops } from '@qm/state';
import { el, sendNotification } from '@qm/dom';
import { showToast } from '@qm/toast';
import { updateMonitoringView } from '@qm/monitor';
import { updateInspectorStatsCard } from '@qm/inspector';
import { applyStatusDots } from '@qm/tree';

// Track whether we've received at least one stats update
let _statsReceived = false;
let _statsWaitTimeout = null;

export function isManualStop(serverId, oldName) {
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

export function detectUnexpectedlyStopped(serverId, oldSet, runningSet) {
  oldSet.forEach(function(oldName) {
    if (!runningSet.has(oldName)) {
      if (!isManualStop(serverId, oldName)) {
        sendNotification('Alert', 'Quadlet container ' + oldName + ' stopped or failed unexpectedly');
      }
    }
  });
}

export function cacheServerStats(data) {
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
export function handleStatsError(e) {
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

export function handleStatsUpdate(e) {
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

export function updatePollHealth(data) {
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

export function applyPollHealthBadges() {
  Object.keys(_pollHealthState).forEach(function(serverId) {
    updatePollHealth(_pollHealthState[serverId]);
  });
}

export function updateCycleIndicator(cycle) {
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

export function fetchPollHealthSnapshot() {
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

export function handleQuadletsChanged(data) {
  const container = document.querySelector(
    '.server-quadlet-tree[data-server-id="' + data.server_id + '"]'
  );
  if (!container) return;
  htmx.ajax('GET', '/api/quadlets/' + data.server_id,
            { target: container, swap: 'innerHTML' });
}

export function createStatsErrorDOM(serverName, errorMsg) {
  return el('div', { className: 'p-4 text-danger' }, [
    el('div', { className: 'font-bold mb-1' }, '⚠ Stats unavailable for ' + (serverName || 'server')),
    el('div', { className: 'text-xs text-muted' }, errorMsg || 'Unknown error'),
    el('div', { className: 'text-xs text-muted mt-1' }, 'Will retry automatically…')
  ]);
}

// ── SSE Connection ───────────────────────────────────────
export function connectSSE() {
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
        handleQuadletsChanged(JSON.parse(e.data));
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

export function startStatsWaitTimeout() {
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
}
