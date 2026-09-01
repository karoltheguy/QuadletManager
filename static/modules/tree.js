/* global htmx */
/**
 * Quadlet tree sidebar: server collapse, selection state, status dots,
 * and file context menus.
 */

import { state, lastStatsPerServer, runningContainersBySid } from '@qm/state';
import { unitNameFor } from '@qm/units';
import { setupModalDismissal } from '@qm/modals';
import { updateInspectorStatsCard, updateInspectorActivityLog } from '@qm/inspector';

// ── Server Collapse ───────────────────────────────────────
export function toggleServerCollapse(serverId) {
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

export function restoreServerCollapseStates() {
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

export function handleServerCollapseKey(e, li, sid) {
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
        toggleServerCollapse(sid);
    }
}

function handleGlobalKeydown(e) {
    const toggle = e.target.closest('.server-row-toggle');
    if (!toggle) return;
    const li = toggle.closest('li[data-server-id]');
    if (!li) return;
    handleServerCollapseKey(e, li, li.dataset.serverId);
}

export function initTree() {
    document.addEventListener('keydown', handleGlobalKeydown);
}

// Mark the clicked quadlet tree button as selected (inset state).
// Called from the delegated 'select-quadlet' action in main.js.
export function setSelectedQuadletBtn(el) {
    document.querySelectorAll('.quadlet-tree-btn.is-selected')
        .forEach(function (b) { b.classList.remove('is-selected'); });
    if (el) el.classList.add('is-selected');
}

// Re-apply the .is-selected class after htmx swaps the quadlet tree.
// Source of truth is state._selectedContainerStem / _selectedContainerServerId,
// set by selectContainerStem() — the editor pane is the real state, we're
// just re-syncing the sidebar visual to match.
export function reapplyQuadletSelection() {
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
export function restoreQuadletSelection() {
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

// Track which server the user is currently working in.
// The stats chart only renders updates for this server.
// null = show whichever server reports first (auto-set on first update).

// Currently selected container stem in the inspector (lowercase).
// Set to true after the saved quadlet selection has been restored once,
// so subsequent htmx:afterSwap tree re-renders don't override user clicks.

export function selectContainerStem(stem, serverId, scope, type) {
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

// Called from quadlet_tree.html when the user clicks a file button.
export function setActiveServer(serverId) {
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
export function applyStatusDots(serverId) {
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

// ── File Deletion ─────────────────────────────────────────
let _ctxMenu = null;

export function showFileContextMenu(event, serverId, path, scope) {
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
        setSelectedQuadletBtn(treeBtn || null);
        setActiveServer(serverId);
        selectContainerStem(stem, serverId, scope, quadletType);
        htmx.ajax('GET', '/api/file/' + serverId + '?path=' + encodeURIComponent(path) + '&scope=' + encodeURIComponent(scope) + '&name=' + encodeURIComponent(fileName), {
            target: '#editor-pane',
            swap: 'outerHTML'
        });
        document.body.dispatchEvent(new CustomEvent('qm:switch-tab', {
            detail: { tabId: 'containers' }
        }));
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
        confirmDeleteFile(serverId, path, scope);
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

export function confirmDeleteFile(serverId, path, scope) {
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
        executeDeleteFile(serverId, path, scope);
    });
    btnContainer.appendChild(deleteBtn);

    content.appendChild(btnContainer);
    modal.appendChild(content);
    document.body.appendChild(modal);
    setupModalDismissal('delete-confirm-modal');
}

export async function executeDeleteFile(serverId, path, scope) {
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
