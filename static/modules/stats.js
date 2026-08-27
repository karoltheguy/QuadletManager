/**
 * Container stats table, fleet counts, and monitor summary strip.
 */

import { state } from '@qm/state';
import { setStatText } from '@qm/dom';
import { chartColorFor, applySwatchState, toggleChartSelection } from '@qm/charts';

// U+2014 EM DASH: the "nothing reported yet" placeholder, matching what the
// stats engine sends for container fields it could not read.
const STAT_PLACEHOLDER = '\u2014';

export function parsePercent(val) {
    if (typeof val === 'string') {
        return Number.parseFloat(val.replaceAll('%', '')) || 0;
    }
    return Number.parseFloat(val) || 0;
}

export function getPercentClass(val) {
    if (val >= 80) return 'cell-danger';
    if (val >= 60) return 'cell-warn';
    return '';
}

// The default only covers `undefined`, which is all this needs: the stats
// engine sets `health` from `health_map.get(name, "")` and always sends a
// string, so a null never reaches here.
export function getHealthBadgeInfo(health = '') {
    if (health === '') return { badgeClass: 'running', label: 'running' };
    if (health === 'healthy') return { badgeClass: 'healthy', label: health };
    if (health === 'starting') return { badgeClass: 'starting', label: health };
    return { badgeClass: 'unhealthy', label: health };
}

// The Monitor table joins each container to its systemd unit by the unit name
// the stats engine attaches to the container. A server that has not reported
// units yet indexes to null, which renders as a placeholder rather than as a
// container with no unit.
export function buildUnitIndex(units) {
    if (units === undefined || units === null) return null;
    const index = new Map();
    units.forEach(function(u) {
        if (u?.unit) index.set(u.unit, u);
    });
    return index;
}

export function getUnitBadgeInfo(activeState = '') {
    if (activeState === 'failed') return { badgeClass: 'unit-failed', label: activeState };
    if (activeState === 'active') return { badgeClass: 'unit-active', label: activeState };
    return { badgeClass: 'unit-other', label: activeState || STAT_PLACEHOLDER };
}

// A stopped systemd unit has no running container, so the stats engine never
// reports it among containers. The Monitor table still needs a row for it, so
// we synthesize placeholder rows for any unit that no container has claimed.
export function mergeUnitRows(containers, units) {
    if (units === undefined || units === null) return containers;
    const claimed = new Set();
    containers.forEach(function(c) {
        if (c.unit) claimed.add(c.unit);
        // A container whose PODMAN_SYSTEMD_UNIT label is missing still belongs
        // to its unit. Quadlet names the container "systemd-<base>" unless
        // ContainerName= overrides it, so the name stem claims the unit too,
        // or the container would be drawn twice: once real, once synthesized.
        const stem = (c.name || '').replace(/^systemd-/, '');
        if (stem) claimed.add(stem + '.service');
    });
    const synthesized = [];
    units.forEach(function(u) {
        if (u.unit && !claimed.has(u.unit)) {
            synthesized.push({
                name: u.unit.replace(/\.service$/, ''),
                unit: u.unit,
                health: '',
                not_running: true,
                cpu: STAT_PLACEHOLDER,
                mem: STAT_PLACEHOLDER,
                mem_usage: STAT_PLACEHOLDER,
                net_io: STAT_PLACEHOLDER,
                pids: STAT_PLACEHOLDER
            });
        }
    });
    return containers.concat(synthesized);
}

export function applyPercentSeverity(td, severityClass) {
    if (!severityClass) return;
    const glyph = severityClass === 'cell-danger' ? '▲' : '●';
    const word = severityClass === 'cell-danger' ? 'high' : 'elevated';

    const flag = document.createElement('span');
    flag.className = 'cell-flag';
    flag.setAttribute('aria-hidden', 'true');
    flag.textContent = glyph;
    td.appendChild(flag);

    const hidden = document.createElement('span');
    hidden.className = 'visually-hidden';
    hidden.textContent = word;
    td.appendChild(hidden);
}

// A synthesized row stands for a unit with no running container, so it has no
// health to report; its status comes from the systemd state instead.
export function getStatusBadgeInfo(c, unitRec) {
    if (c.not_running) return getUnitBadgeInfo(unitRec?.active_state);
    return getHealthBadgeInfo(c.health);
}

export function renderContainerRow(c, unitIndex) {
    const cpuClass = getPercentClass(parsePercent(c.cpu));
    const memClass = getPercentClass(parsePercent(c.mem));
    const unitRec = unitIndex && c.unit ? unitIndex.get(c.unit) : null;
    const badgeInfo = getStatusBadgeInfo(c, unitRec);

    const tr = document.createElement('tr');
    tr.className = 'border-b';

    const tdSwatch = document.createElement('td');
    tdSwatch.className = 'p-4 chart-swatch-cell';
    if (!c.not_running) {
        const swatchBtn = document.createElement('button');
        swatchBtn.type = 'button';
        swatchBtn.dataset.container = c.name;
        swatchBtn.style.backgroundColor = chartColorFor(c.name);
        swatchBtn.setAttribute('aria-label', 'Toggle ' + c.name + ' in the history charts');
        applySwatchState(swatchBtn, c.name);
        swatchBtn.addEventListener('click', function() {
            toggleChartSelection(c.name);
        });
        tdSwatch.appendChild(swatchBtn);
    }
    tr.appendChild(tdSwatch);

    const tdName = document.createElement('td');
    tdName.className = 'text-left p-4 text-accent font-semibold';
    tdName.textContent = c.name;
    tr.appendChild(tdName);

    const tdStatus = document.createElement('td');
    tdStatus.className = 'p-4 text-left';
    const badgeSpan = document.createElement('span');
    badgeSpan.className = 'stat-badge ' + badgeInfo.badgeClass;
    badgeSpan.textContent = badgeInfo.label;
    tdStatus.appendChild(badgeSpan);
    tr.appendChild(tdStatus);

    const tdUnit = document.createElement('td');
    tdUnit.className = 'p-4 text-left';
    if (unitRec) {
        const unitInfo = getUnitBadgeInfo(unitRec.active_state);
        const unitBadge = document.createElement('span');
        unitBadge.className = 'stat-badge ' + unitInfo.badgeClass;
        unitBadge.textContent = unitInfo.label;
        tdUnit.appendChild(unitBadge);
        if (unitRec.n_restarts > 0) {
            // The restart count reads as a bare number to a screen reader, so
            // name it with a visually-hidden label.
            const count = document.createElement('span');
            count.className = 'cell-flag';
            count.setAttribute('aria-hidden', 'true');
            count.textContent = '\u00d7' + unitRec.n_restarts;
            tdUnit.appendChild(count);

            const hidden = document.createElement('span');
            hidden.className = 'visually-hidden';
            hidden.textContent = unitRec.n_restarts + ' restarts';
            tdUnit.appendChild(hidden);
        }
    } else {
        tdUnit.textContent = STAT_PLACEHOLDER;
    }
    tr.appendChild(tdUnit);

    const tdCpu = document.createElement('td');
    tdCpu.className = 'p-4 text-right' + (cpuClass ? ' ' + cpuClass : '');
    tdCpu.textContent = c.cpu;
    applyPercentSeverity(tdCpu, cpuClass);
    tr.appendChild(tdCpu);

    const tdMem = document.createElement('td');
    tdMem.className = 'p-4 text-right' + (memClass ? ' ' + memClass : '');
    tdMem.textContent = c.mem;
    applyPercentSeverity(tdMem, memClass);
    tr.appendChild(tdMem);

    const tdNet = document.createElement('td');
    tdNet.className = 'p-4 text-right net-io-cell';
    tdNet.textContent = c.net_io;
    tr.appendChild(tdNet);

    return tr;
}

export function renderContainerStatsTable(tableElId, data) {
    const tableEl = document.getElementById(tableElId);
    if (!tableEl) return;

    tableEl.innerHTML = '';
    const containers = data.containers || [];

    if (containers.length === 0) {
        const emptyDiv = document.createElement('div');
        emptyDiv.className = 'p-4 text-muted italic';
        emptyDiv.textContent = 'No containers running on ' + (data.server_name || 'server');
        tableEl.appendChild(emptyDiv);
        return;
    }

    const table = document.createElement('table');
    table.className = 'w-full';

    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    headerRow.className = 'text-muted';

    const headers = [
        { text: 'Series color', align: 'left', visuallyHidden: true },
        { text: 'Container', align: 'left' },
        { text: 'Status', align: 'left' },
        { text: 'Unit', align: 'left' },
        { text: 'CPU', align: 'right' },
        { text: 'MEM', align: 'right' },
        { text: 'NET I/O', align: 'right' }
    ];

    headers.forEach(function(h) {
        const th = document.createElement('th');
        th.className = (h.align === 'left' ? 'text-left p-4' : 'p-4 text-right');
        th.scope = 'col';
        if (h.visuallyHidden) {
            const label = document.createElement('span');
            label.className = 'visually-hidden';
            label.textContent = h.text;
            th.appendChild(label);
        } else {
            th.textContent = h.text;
        }
        headerRow.appendChild(th);
    });

    // <caption> must be the table's first child per the HTML spec, so it is
    // appended before <thead>.
    const caption = document.createElement('caption');
    caption.className = 'visually-hidden';
    caption.textContent = 'Container resource usage for ' + (data.server_name || 'server');
    table.appendChild(caption);

    thead.appendChild(headerRow);
    table.appendChild(thead);

    const unitIndex = buildUnitIndex(data.units);

    const tbody = document.createElement('tbody');
    containers.forEach(function(c) {
        const tr = renderContainerRow(c, unitIndex);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableEl.appendChild(table);

    const footerDiv = document.createElement('div');
    footerDiv.className = 'p-4 text-muted text-right text-xs';
    footerDiv.textContent = data.server_name || '';
    tableEl.appendChild(footerDiv);
}

// "N of M shown" next to the filter box. Both counts come from the running
// container list, so this reports what the table and charts are showing and
// not the stopped containers the glance bar also counts.
export function updateFilterCount(shown, total) {
  const el = document.getElementById('monitor-filter-count');
  if (!el) return;

  if (!state.monitorContainerFilter) {
    el.hidden = true;
    el.textContent = '';
    return;
  }

  el.textContent = shown + ' of ' + total + ' shown';
  el.hidden = false;
}

export function computeServerTotals(containers) {
  const list = containers || [];
  const totals = { cpu: 0, mem: 0 };
  list.forEach(function(c) {
    totals.cpu += parsePercent(c.cpu);
    totals.mem += parsePercent(c.mem);
  });
  return totals;
}

// Units are the source of truth for the fleet counts; containers only supply
// health and load. A server that has not reported units yet shows placeholders
// rather than a misleading zero.
export function computeUnitCounts(units) {
  if (units === undefined || units === null) {
    return {
      total: STAT_PLACEHOLDER,
      running: STAT_PLACEHOLDER,
      stopped: STAT_PLACEHOLDER,
      failed: STAT_PLACEHOLDER
    };
  }
  // Units are matched against the same lowercase substring filter used for
  // container names, keyed off the unit stem (name without ".service").
  const filteredUnits = units.filter(function(u) {
    const stem = (u.unit || '').replace(/\.service$/, '').toLowerCase();
    return !state.monitorContainerFilter || stem.includes(state.monitorContainerFilter);
  });
  const total = filteredUnits.length;
  const running = filteredUnits.filter(function(u) { return u.active_state === 'active'; }).length;
  // A failed unit is not simply "stopped": stopped stays total - running so the
  // three load counts still add up, and failed overlaps it as its own signal.
  const failed = filteredUnits.filter(function(u) { return u.active_state === 'failed'; }).length;
  return { total: total, running: running, stopped: total - running, failed: failed };
}

// The 'danger' class carries the unhealthy state by colour alone, so repeat it
// as a glyph for anyone who cannot perceive that.
export function renderUnhealthyStat(unhealthy) {
  const elUnhealthy = document.getElementById('mstat-unhealthy');
  if (!elUnhealthy) return;
  elUnhealthy.textContent = unhealthy;
  elUnhealthy.classList.toggle('danger', unhealthy > 0);
  if (unhealthy > 0) {
    const flag = document.createElement('span');
    flag.className = 'monitor-stat-flag';
    flag.setAttribute('aria-hidden', 'true');
    flag.textContent = '⚠';
    elUnhealthy.appendChild(flag);
  }
}

// Same colour-plus-glyph treatment as the unhealthy stat, for the same reason.
export function renderFailedStat(failed) {
  const elFailed = document.getElementById('mstat-failed');
  if (!elFailed) return;
  elFailed.textContent = failed;
  elFailed.classList.toggle('danger', failed > 0);
  if (failed > 0) {
    const flag = document.createElement('span');
    flag.className = 'monitor-stat-flag';
    flag.setAttribute('aria-hidden', 'true');
    flag.textContent = '\u26a0';
    elFailed.appendChild(flag);
  }
}

export function healthAnnouncement(unhealthy) {
  if (unhealthy === 0) return 'All containers healthy';
  if (unhealthy === 1) return '1 container unhealthy';
  return unhealthy + ' containers unhealthy';
}

// Last unhealthy count announced to #monitor-health-status, so repeated
// SSE ticks with an unchanged count do not re-trigger the live region.
let lastAnnouncedUnhealthy = null;

// Only rewrite the live region's text when the unhealthy count actually
// changes, so unchanged SSE ticks do not re-announce the same state.
export function announceHealthChange(unhealthy) {
  if (unhealthy === lastAnnouncedUnhealthy) return;
  const elHealthStatus = document.getElementById('monitor-health-status');
  if (elHealthStatus) {
    elHealthStatus.textContent = healthAnnouncement(unhealthy);
  }
  lastAnnouncedUnhealthy = unhealthy;
}

export function updateSummaryStrip(data) {
  const containers = data.containers || [];
  const counts = computeUnitCounts(data.units);
  const unhealthy = containers.filter(function(c) {
    return c.health && c.health !== 'healthy';
  }).length;
  const totals = computeServerTotals(containers);
  const hasLoad = containers.length > 0;

  setStatText('mstat-total', counts.total);
  setStatText('mstat-running', counts.running);
  setStatText('mstat-stopped', counts.stopped);
  renderUnhealthyStat(unhealthy);
  renderFailedStat(counts.failed);
  setStatText('mstat-cpu', hasLoad ? totals.cpu.toFixed(1) + '%' : STAT_PLACEHOLDER);
  setStatText('mstat-mem', hasLoad ? totals.mem.toFixed(1) + '%' : STAT_PLACEHOLDER);

  const elBar = document.getElementById('monitor-stat-bar');
  if (elBar) elBar.style.display = '';

  announceHealthChange(unhealthy);
}
