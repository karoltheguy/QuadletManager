/**
 * Real-time log streaming over WebSocket and log tab management.
 */

import { state, lastStatsPerServer, _logTabs } from '@qm/state';
import { openBottomPanel, switchBottomTab, refreshSessionsStripVisibility } from '@qm/panel';
import { unitNameFor } from '@qm/units';

// ── Real-time Logs WebSocket ─────────────────────────────
export function showLogMessage(msg) {
    const hint = document.getElementById('log-empty-hint');
    if (hint) {
        hint.textContent = msg;
        hint.classList.remove('hidden');
        setTimeout(function() {
            if (hint.textContent === msg) {
                hint.textContent = 'Click "Tail Logs" to start streaming a container\'s logs';
            }
        }, 3000);
    }
}

export function tailLogsFromPanel() {
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
    if (_logTabs.has(tabKey)) {
        switchLogTab(tabKey);
        return;
    }

    createLogTab(tabKey, serverId, unitName, scope);
}

export function createLogTab(tabKey, serverId, unitName, scope) {
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
    if (hint) hint.classList.add('hidden');

    const sinceSelect = document.getElementById('log-since-select');
    const since = sinceSelect ? sinceSelect.value : '15m';

    _logTabs.set(tabKey, { logDiv: logDiv, tabEl: tabEl, paneEl: paneEl, serverId: serverId, unitName: unitName, scope: scope, since: since });
    switchLogTab(tabKey);

    // ── WebSocket ───────────────────────────────────────
    openLogSocket(tabKey);
}

export function openLogSocket(tabKey) {
    const entry = _logTabs.get(tabKey);
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
    _logTabs.set(tabKey, entry);
}

export function switchLogTab(key) {
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
        const entry = _logTabs.get(key);
        sinceSelect.value = entry?.since || '15m';
    }

    switchBottomTab('logs');
}

export function handleClosedLogTabFallback(key) {
    if (_logTabs.size === 0) {
        const hint = document.getElementById('log-empty-hint');
        if (hint) hint.classList.remove('hidden');
        state._activeLogTabKey = null;
    } else if (state._activeLogTabKey === key) {
        switchLogTab(_logTabs.keys().next().value);
    }
    refreshSessionsStripVisibility();
}

export function closeLogTab(key) {
    const session = _logTabs.get(key);
    if (!session) return;

    if (session.ws && session.ws.readyState !== WebSocket.CLOSED) {
        session.ws.send('STOP');
        session.ws.close();
    }
    session.tabEl?.remove();
    session.paneEl?.remove();

    _logTabs.delete(key);
    handleClosedLogTabFallback(key);
}

export function initLogs() {
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
            const entry = key ? _logTabs.get(key) : null;
            if (!entry) return;

            entry.since = value;
            if (entry.ws) entry.ws.close();
            if (entry.logDiv) entry.logDiv.textContent = 'Reconnecting…\n';
            openLogSocket(key);
        });
    }
}
