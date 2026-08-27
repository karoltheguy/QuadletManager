/**
 * Inspector pane: stats card, activity log, and expand/collapse toggle.
 */

import { state, lastStatsPerServer, runningContainersBySid } from '@qm/state';
import { el, getRelativeTime } from '@qm/dom';

export function updateInspectorStatsCard() {
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

export function updateInspectorActivityLog() {
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

// ── Inspector Expand / Collapse Toggle ───────────────────
export function syncInspectorToggleBtn() {
  const btn = document.getElementById('inspector-expand-btn');
  if (!btn) return;
  const expanded = document.body.classList.contains('inspector-expanded');
  btn.title = expanded ? 'Restore inspector' : 'Collapse inspector';
  btn.setAttribute('aria-label', btn.title);
}

export function toggleInspectorExpand() {
  const expanded = document.body.classList.toggle('inspector-expanded');
  localStorage.setItem('qm-inspector-expanded', expanded ? 'true' : 'false');
  syncInspectorToggleBtn();
  // Monaco must re-layout after the inspector width changes
  if (window.editor) window.editor.layout();
}
