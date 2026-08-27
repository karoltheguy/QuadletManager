/**
 * Bottom panel management, tab switching, and resizable layout handles.
 */

import { _terminalTabs, state } from '@qm/state';

// ── Bottom Panel Management ───────────────────────────────
export function openBottomPanel(tab) {
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
        const session = _terminalTabs.get(key);
        if (session?.fitAddon) session.fitAddon.fit();
    }
}

export function fitActiveTerminal() {
    const key = state._activeTerminalTabKey;
    if (!key) return;
    const session = _terminalTabs.get(key);
    if (session?.fitAddon) {
        session.fitAddon.fit();
    }
}

export function toggleBottomPanel() {
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

export function toggleBottomPanelExpand() {
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
        const session = _terminalTabs.get(key);
        if (session?.fitAddon) session.fitAddon.fit();
    }
}

export function switchBottomTab(pane) {
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
            const session = _terminalTabs.get(key);
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

export function initPanel() {
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
}

// ── Resizable Panel Handles ──────────────────────────────
export function initResizableHandles() {
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
                if (_rk) { const _rs = _terminalTabs.get(_rk); if (_rs?.fitAddon) _rs.fitAddon.fit(); }
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
                if (_uk) { const _us = _terminalTabs.get(_uk); if (_us?.fitAddon) _us.fitAddon.fit(); }
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }
}
