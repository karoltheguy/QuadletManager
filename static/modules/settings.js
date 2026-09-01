/**
 * Settings page: server row edit toggle and drag-to-reorder.
 */

export function toggleServerEdit(serverId) {
  const row = document.getElementById('server-edit-row-' + serverId);
  if (row) row.style.display = row.style.display === 'none' ? '' : 'none';
}

// Resolve the server row an event happened in, but only when it belongs to the
// live #servers-tbody. Every listener below is on `document`, so this guard is
// the only thing keeping a drag elsewhere on the page out of the reorder logic.
function serverRowFrom(e) {
  const tbody = document.getElementById('servers-tbody');
  if (!tbody) return null;
  const row = e.target.closest('tr[data-server-id]');
  if (!row || !tbody.contains(row)) return null;
  return { tbody, row };
}

// templates/partials/settings_servers.html is re-swapped by htmx into #servers-list
// on every server mutation, so the tbody element it binds to is destroyed and recreated.
// A one-time bind to #servers-tbody would be dead after the first swap. Document-level
// delegation survives the swap.
export function initServerReorder() {
  let draggedRow = null;

  document.addEventListener('dragstart', function (e) {
    const hit = serverRowFrom(e);
    if (!hit) return;
    draggedRow = hit.row;
    hit.row.classList.add('dragging');
  });

  document.addEventListener('dragend', function (e) {
    const hit = serverRowFrom(e);
    if (!hit) return;
    if (draggedRow) draggedRow.classList.remove('dragging');
    draggedRow = null;
    hit.tbody.querySelectorAll('tr').forEach(r => r.classList.remove('drag-over'));
  });

  document.addEventListener('dragover', function (e) {
    const hit = serverRowFrom(e);
    if (!hit) return;
    e.preventDefault();
    hit.tbody.querySelectorAll('tr').forEach(r => r.classList.remove('drag-over'));
    if (hit.row !== draggedRow) hit.row.classList.add('drag-over');
  });

  document.addEventListener('dragleave', function (e) {
    const hit = serverRowFrom(e);
    if (!hit) return;
    hit.row.classList.remove('drag-over');
  });

  document.addEventListener('drop', function (e) {
    const hit = serverRowFrom(e);
    if (!hit) return;
    e.preventDefault();
    const { tbody, row: target } = hit;
    if (target === draggedRow || !draggedRow) return;

    target.classList.remove('drag-over');

    // Move dragged row before the target in the DOM
    target.before(draggedRow);

    // Also move its edit row (hidden form row) right after it
    const editRow = document.getElementById('server-edit-row-' + draggedRow.dataset.serverId);
    if (editRow) tbody.insertBefore(editRow, draggedRow.nextSibling);

    // Collect new order from visible data rows
    const order = Array.from(tbody.querySelectorAll('tr[data-server-id]'))
      .map(r => Number.parseInt(r.dataset.serverId, 10));

    fetch('/api/settings/servers/reorder', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order }),
    }).then(res => {
      if (!res.ok) { console.error('Reorder failed', res.status); return; }
      const list = document.getElementById('servers-list');
      if (list) list.dispatchEvent(new CustomEvent('refresh-servers'));
      document.body.dispatchEvent(new CustomEvent('reload-servers'));
    });
  });
}

function renderServerListError(elt, message) {
  const p = document.createElement('p');
  p.className = 'text-danger';
  p.textContent = message;
  const btn = document.createElement('button');
  btn.className = 'btn btn-sm btn-secondary';
  btn.dataset.action = 'retry-servers-list';
  btn.textContent = 'Retry';
  p.appendChild(btn);
  elt.replaceChildren(p);
}

// Replaces two hx-on attributes whose bodies each contained an inline onclick.
// Both the attribute body and that onclick needed 'unsafe-inline'. Delegating
// on document.body survives htmx swaps of #servers-list.
export function initServerListRetry() {
  document.body.addEventListener('htmx:responseError', function (e) {
    const elt = e.detail?.elt || e.target;
    if (elt?.id !== 'servers-list') return;
    renderServerListError(elt, 'Failed to load servers. ');
  });

  document.body.addEventListener('htmx:sendError', function (e) {
    const elt = e.detail?.elt || e.target;
    if (elt?.id !== 'servers-list') return;
    renderServerListError(elt, 'Network error loading servers. ');
  });
}
