/* global Terminal */
/**
 * Real-time interactive terminal over WebSocket (/ws/exec) and tab management.
 */

import { state, _terminalTabs, runningContainersBySid,
         lastStatsPerServer } from '@qm/state';
import { openBottomPanel, switchBottomTab,
         refreshSessionsStripVisibility } from '@qm/panel';
import { tailLogsFromPanel } from '@qm/logs';

// ── Terminal Session Management ──────────────────────────
export function loadFitAddon(callback) {
    callback();
}

export function showTerminalMessage(msg) {
    const hint = document.getElementById('terminal-empty-hint');
    if (hint) {
        hint.textContent = msg;
        hint.classList.remove('hidden');
        setTimeout(function() {
            if (hint.textContent === msg) {
                hint.textContent = 'Select a running container and click Connect';
            }
        }, 3000);
    }
}

export function findActualRunningContainerName(running, stem) {
    let actualName = null;
    running.forEach(function(name) {
        if (name.includes(stem) || stem.includes(name)) {
            actualName = name;
        }
    });
    return actualName;
}

export function getTerminalShellCommand() {
    const shellSelect = document.getElementById('terminal-shell-select');
    const shell = shellSelect ? shellSelect.value : 'bash';
    if (shell === 'custom') {
        const customInput = document.getElementById('terminal-custom-cmd-input');
        return (customInput ? customInput.value.trim() : '') || 'bash';
    }
    return shell;
}

export function connectTerminal() {
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
    if (_terminalTabs.has(tabKey)) {
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

export function createTerminalTab(tabKey, serverId, containerName, cmd, scope) {
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
    if (hint) hint.classList.add('hidden');

    // Toggle DOM visibility BEFORE creating xterm to avoid 0x0 size calculation
    _terminalTabs.set(tabKey, { tabEl: tabEl, paneEl: paneEl, serverId: serverId, containerName: containerName, scope: scope, cmd: cmd });
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

    _terminalTabs.set(tabKey, { term: term, ws: ws, fitAddon: fitAddon, tabEl: tabEl, paneEl: paneEl, serverId: serverId, containerName: containerName, scope: scope, cmd: cmd });

    setTimeout(function() {
        if (ws.readyState === WebSocket.OPEN) {
            fitAddon.fit();
        }
        term.focus();
    }, 10);
}

export function switchTerminalTab(key) {
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

    const session = _terminalTabs.get(key);
    if (session?.fitAddon) {
        setTimeout(function() { session.fitAddon.fit(); }, 50);
    }
}

export function disposeTerminalSession(session) {
    if (session.ws && session.ws.readyState !== WebSocket.CLOSED) {
        session.ws.close();
    }
    try { session.term.dispose(); } catch { /* xterm may throw if initialized on a hidden element */ }
}

export function removeTerminalDOM(session) {
    session.tabEl?.remove();
    session.paneEl?.remove();
}

export function handleClosedTabFallback(key) {
    if (_terminalTabs.size === 0) {
        const hint = document.getElementById('terminal-empty-hint');
        if (hint) hint.classList.remove('hidden');
        state._activeTerminalTabKey = null;
    } else if (state._activeTerminalTabKey === key) {
        switchTerminalTab(_terminalTabs.keys().next().value);
    }
    refreshSessionsStripVisibility();
}

export function closeTerminalTab(key) {
    const session = _terminalTabs.get(key);
    if (!session) return;

    disposeTerminalSession(session);
    removeTerminalDOM(session);

    _terminalTabs.delete(key);
    handleClosedTabFallback(key);
}

export function sessionAddNew() {
    const activeTab = document.querySelector('.bottom-tab.is-active');
    const pane = activeTab ? activeTab.dataset.pane : 'terminal';
    if (pane === 'logs') {
        tailLogsFromPanel();
    } else {
        connectTerminal();
    }
}

export function initTerminal() {
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

    // ── Global window resize handler for the active terminal tab ────────────────
    window.addEventListener('resize', function() {
        const key = state._activeTerminalTabKey;
        if (!key) return;
        const session = _terminalTabs.get(key);
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
}
